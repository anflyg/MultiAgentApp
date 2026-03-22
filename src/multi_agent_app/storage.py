from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from . import models

DEFAULT_WORKSPACE_NAME = "Default"
DEFAULT_WORKSPACE_DESCRIPTION = "Default workspace for uncategorized work."
ACTIVE_WORKSPACE_STATE_KEY = "active_workspace_id"


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Storage:
    """Simple SQLite-backed persistence layer with lightweight schema upgrades."""

    def __init__(self, db_path: str = "multi_agent.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                workspace_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                owner_agent TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS agent_actions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'result',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'session',
                kind TEXT NOT NULL DEFAULT 'fact',
                source_agent TEXT,
                task_id TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id),
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS session_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                decision_text TEXT NOT NULL,
                rationale TEXT,
                background TEXT,
                assumptions TEXT,
                risks TEXT,
                alternatives_considered TEXT,
                consequences TEXT,
                follow_up_notes TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                owner TEXT,
                created_at TEXT NOT NULL,
                effective_from TEXT,
                review_date TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS decision_candidates (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                candidate_text TEXT NOT NULL,
                rationale TEXT,
                status TEXT NOT NULL DEFAULT 'proposed',
                owner TEXT,
                created_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS decision_links (
                id TEXT PRIMARY KEY,
                from_decision_id TEXT NOT NULL,
                to_decision_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(from_decision_id) REFERENCES decisions(id),
                FOREIGN KEY(to_decision_id) REFERENCES decisions(id),
                UNIQUE(from_decision_id, to_decision_id, relation_type)
            );
            CREATE TABLE IF NOT EXISTS decision_suggestions (
                id TEXT PRIMARY KEY,
                source_decision_id TEXT NOT NULL,
                target_decision_id TEXT NOT NULL,
                suggestion_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_decision_id) REFERENCES decisions(id),
                FOREIGN KEY(target_decision_id) REFERENCES decisions(id),
                UNIQUE(source_decision_id, target_decision_id, suggestion_type)
            );
            CREATE TABLE IF NOT EXISTS reasoning_items (
                id TEXT PRIMARY KEY,
                decision_id TEXT,
                question_id TEXT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'system',
                memory_level TEXT NOT NULL DEFAULT 'private_context',
                created_at TEXT NOT NULL,
                FOREIGN KEY(decision_id) REFERENCES decisions(id),
                FOREIGN KEY(question_id) REFERENCES panel_questions(id)
            );
            CREATE TABLE IF NOT EXISTS panel_questions (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                question_text TEXT,
                topic TEXT NOT NULL,
                session_id TEXT,
                workspace_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
            );
            CREATE TABLE IF NOT EXISTS panel_responses (
                id TEXT PRIMARY KEY,
                question_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                response_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(question_id) REFERENCES panel_questions(id)
            );
            CREATE TABLE IF NOT EXISTS panel_question_analyses (
                id TEXT PRIMARY KEY,
                question_id TEXT NOT NULL UNIQUE,
                assessment_alignment TEXT NOT NULL,
                assessment_reason TEXT NOT NULL,
                challenge_points TEXT NOT NULL DEFAULT '[]',
                question_interpretation TEXT,
                relevant_context TEXT NOT NULL DEFAULT '{}',
                per_role_analysis TEXT NOT NULL DEFAULT '{}',
                tensions TEXT NOT NULL DEFAULT '[]',
                combined_recommendation TEXT NOT NULL,
                suggested_next_step TEXT NOT NULL,
                likely_requires_new_decision TEXT NOT NULL,
                decision_status_assessment TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(question_id) REFERENCES panel_questions(id)
            );
            CREATE TABLE IF NOT EXISTS panel_question_context_decisions (
                question_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                PRIMARY KEY(question_id, decision_id),
                FOREIGN KEY(question_id) REFERENCES panel_questions(id),
                FOREIGN KEY(decision_id) REFERENCES decisions(id)
            );
            """
        )
        self._ensure_column("sessions", "workspace_id", "TEXT")
        self._ensure_column("sessions", "status", "TEXT NOT NULL DEFAULT 'active'")
        self._ensure_column("tasks", "priority", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("tasks", "owner_agent", "TEXT")
        self._ensure_column("agent_actions", "session_id", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("agent_actions", "kind", "TEXT NOT NULL DEFAULT 'result'")
        self._ensure_column("memory_items", "scope", "TEXT NOT NULL DEFAULT 'session'")
        self._ensure_column("memory_items", "kind", "TEXT NOT NULL DEFAULT 'fact'")
        self._ensure_column("memory_items", "source_agent", "TEXT")
        self._ensure_column("memory_items", "task_id", "TEXT")
        self._ensure_column("decisions", "rationale", "TEXT")
        self._ensure_column("decisions", "background", "TEXT")
        self._ensure_column("decisions", "assumptions", "TEXT")
        self._ensure_column("decisions", "risks", "TEXT")
        self._ensure_column("decisions", "alternatives_considered", "TEXT")
        self._ensure_column("decisions", "consequences", "TEXT")
        self._ensure_column("decisions", "follow_up_notes", "TEXT")
        self._ensure_column("decisions", "status", "TEXT NOT NULL DEFAULT 'active'")
        self._ensure_column("decisions", "owner", "TEXT")
        self._ensure_column("decisions", "effective_from", "TEXT")
        self._ensure_column("decisions", "review_date", "TEXT")
        self._ensure_column("decisions", "tags", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("decision_candidates", "rationale", "TEXT")
        self._ensure_column("decision_candidates", "status", "TEXT NOT NULL DEFAULT 'proposed'")
        self._ensure_column("decision_candidates", "owner", "TEXT")
        self._ensure_column("decision_candidates", "tags", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("reasoning_items", "source_type", "TEXT NOT NULL DEFAULT 'system'")
        self._ensure_column(
            "reasoning_items", "memory_level", "TEXT NOT NULL DEFAULT 'private_context'"
        )
        self._ensure_column("panel_questions", "question_text", "TEXT")
        self._ensure_column("panel_questions", "workspace_id", "TEXT")
        self._ensure_column("panel_questions", "status", "TEXT NOT NULL DEFAULT 'open'")
        self._ensure_column("panel_question_analyses", "question_interpretation", "TEXT")
        self._ensure_column(
            "panel_question_analyses", "relevant_context", "TEXT NOT NULL DEFAULT '{}'"
        )
        self._ensure_column(
            "panel_question_analyses", "per_role_analysis", "TEXT NOT NULL DEFAULT '{}'"
        )
        self._ensure_column("panel_question_analyses", "tensions", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column(
            "panel_question_analyses",
            "decision_status_assessment",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        default_workspace = self._get_or_create_default_workspace()
        self._conn.execute(
            "UPDATE sessions SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
            (default_workspace.id,),
        )
        active_workspace = self._read_active_workspace()
        if active_workspace is None or self.get_workspace(active_workspace) is None:
            self._write_state(ACTIVE_WORKSPACE_STATE_KEY, default_workspace.id)
        self._conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_columns = {row["name"] for row in rows}
        if column not in existing_columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _write_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
            (key, value),
        )

    def _read_state(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (key,),
        ).fetchone()
        return row["value"] if row else None

    def _read_active_workspace(self) -> str | None:
        return self._read_state(ACTIVE_WORKSPACE_STATE_KEY)

    def _workspace_from_row(self, row: sqlite3.Row) -> models.Workspace:
        return models.Workspace(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=_from_iso(row["created_at"]),
        )

    def _get_or_create_default_workspace(self) -> models.Workspace:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE name = ?",
            (DEFAULT_WORKSPACE_NAME,),
        ).fetchone()
        if row:
            return self._workspace_from_row(row)
        workspace = models.Workspace(
            name=DEFAULT_WORKSPACE_NAME,
            description=DEFAULT_WORKSPACE_DESCRIPTION,
        )
        self._conn.execute(
            """
            INSERT INTO workspaces (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (workspace.id, workspace.name, workspace.description, _to_iso(workspace.created_at)),
        )
        return workspace

    def create_workspace(self, name: str, description: str = "") -> models.Workspace:
        normalized_name = " ".join(name.strip().split())
        if not normalized_name:
            raise ValueError("Workspace name cannot be empty")
        workspace = models.Workspace(
            name=normalized_name,
            description=description.strip(),
        )
        self._conn.execute(
            """
            INSERT INTO workspaces (id, name, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (workspace.id, workspace.name, workspace.description, _to_iso(workspace.created_at)),
        )
        self._conn.commit()
        return workspace

    def list_workspaces(self) -> List[models.Workspace]:
        rows = self._conn.execute(
            "SELECT * FROM workspaces ORDER BY created_at",
        ).fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def get_workspace(self, workspace_id: str) -> models.Workspace | None:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        return self._workspace_from_row(row)

    def get_workspace_by_name(self, name: str) -> models.Workspace | None:
        row = self._conn.execute(
            "SELECT * FROM workspaces WHERE lower(name) = lower(?)",
            (name.strip(),),
        ).fetchone()
        if row is None:
            return None
        return self._workspace_from_row(row)

    def get_active_workspace(self) -> models.Workspace:
        active_workspace_id = self._read_active_workspace()
        workspace = (
            self.get_workspace(active_workspace_id)
            if active_workspace_id is not None
            else None
        )
        if workspace is not None:
            return workspace
        workspace = self._get_or_create_default_workspace()
        self._write_state(ACTIVE_WORKSPACE_STATE_KEY, workspace.id)
        self._conn.commit()
        return workspace

    def set_active_workspace(self, workspace_id: str) -> models.Workspace:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace '{workspace_id}' was not found")
        self._write_state(ACTIVE_WORKSPACE_STATE_KEY, workspace.id)
        self._conn.commit()
        return workspace

    def add_session(self, session: models.Session) -> None:
        workspace_id = session.workspace_id or self.get_active_workspace().id
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sessions (id, name, workspace_id, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session.id, session.name, workspace_id, session.status, _to_iso(session.created_at)),
        )
        self._conn.commit()

    def update_session_status(self, session_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (status, session_id),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> Optional[models.Session]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return models.Session(
            id=row["id"],
            name=row["name"],
            workspace_id=row["workspace_id"] if "workspace_id" in row.keys() else None,
            status=row["status"],
            created_at=_from_iso(row["created_at"]),
        )

    def list_sessions(self) -> List[models.Session]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [
            models.Session(
                id=row["id"],
                name=row["name"],
                workspace_id=row["workspace_id"] if "workspace_id" in row.keys() else None,
                status=row["status"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def list_sessions_for_workspace(self, workspace_id: str) -> List[models.Session]:
        rows = self._conn.execute(
            """
            SELECT * FROM sessions
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        ).fetchall()
        return [
            models.Session(
                id=row["id"],
                name=row["name"],
                workspace_id=row["workspace_id"] if "workspace_id" in row.keys() else None,
                status=row["status"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def add_task(self, task: models.Task) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO tasks (
                id, session_id, description, priority, owner_agent, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.session_id,
                task.description,
                task.priority,
                task.owner_agent,
                task.status,
                _to_iso(task.created_at),
            ),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> Optional[models.Task]:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return self._task_from_row(row)

    def update_task(self, task: models.Task) -> None:
        self._conn.execute(
            """
            UPDATE tasks
            SET session_id = ?, description = ?, priority = ?, owner_agent = ?, status = ?, created_at = ?
            WHERE id = ?
            """,
            (
                task.session_id,
                task.description,
                task.priority,
                task.owner_agent,
                task.status,
                _to_iso(task.created_at),
                task.id,
            ),
        )
        self._conn.commit()

    def update_task_status(self, task_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        self._conn.commit()

    def update_task_owner(self, task_id: str, owner_agent: str | None) -> None:
        self._conn.execute(
            "UPDATE tasks SET owner_agent = ? WHERE id = ?",
            (owner_agent, task_id),
        )
        self._conn.commit()

    def list_tasks(self, session_id: str) -> List[models.Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def _task_from_row(self, row: sqlite3.Row) -> models.Task:
        return models.Task(
            id=row["id"],
            session_id=row["session_id"],
            description=row["description"],
            priority=row["priority"],
            owner_agent=row["owner_agent"],
            status=row["status"],
            created_at=_from_iso(row["created_at"]),
        )

    def add_agent_action(self, action: models.AgentAction) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO agent_actions (
                id, session_id, task_id, agent_name, kind, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.id,
                action.session_id,
                action.task_id,
                action.agent_name,
                action.kind,
                action.content,
                _to_iso(action.created_at),
            ),
        )
        self._conn.commit()

    def list_agent_actions(self, task_id: str) -> List[models.AgentAction]:
        rows = self._conn.execute(
            "SELECT * FROM agent_actions WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def list_agent_actions_for_session(self, session_id: str) -> List[models.AgentAction]:
        rows = self._conn.execute(
            "SELECT * FROM agent_actions WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def _action_from_row(self, row: sqlite3.Row) -> models.AgentAction:
        return models.AgentAction(
            id=row["id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            agent_name=row["agent_name"],
            kind=row["kind"],
            content=row["content"],
            created_at=_from_iso(row["created_at"]),
        )

    def add_memory_items(self, items: Iterable[models.MemoryItem]) -> None:
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO memory_items (
                id, session_id, scope, kind, source_agent, task_id, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.id,
                    item.session_id,
                    item.scope,
                    item.kind,
                    item.source_agent,
                    item.task_id,
                    item.content,
                    _to_iso(item.created_at),
                )
                for item in items
            ],
        )
        self._conn.commit()

    def add_session_event(self, event: models.SessionEvent) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO session_events (id, session_id, event_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event.id, event.session_id, event.event_type, event.message, _to_iso(event.created_at)),
        )
        self._conn.commit()

    def add_reasoning_item(self, item: models.ReasoningItem) -> None:
        if not item.decision_id and not item.question_id:
            raise ValueError("Reasoning item must reference either decision_id or question_id")
        self._conn.execute(
            """
            INSERT OR REPLACE INTO reasoning_items (
                id, decision_id, question_id, kind, content, source_type, memory_level, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.decision_id,
                item.question_id,
                item.kind,
                item.content,
                item.source_type,
                item.memory_level,
                _to_iso(item.created_at),
            ),
        )
        self._conn.commit()

    def list_reasoning_items_for_decision(self, decision_id: str) -> List[models.ReasoningItem]:
        rows = self._conn.execute(
            """
            SELECT * FROM reasoning_items
            WHERE decision_id = ?
            ORDER BY created_at
            """,
            (decision_id,),
        ).fetchall()
        return [self._reasoning_item_from_row(row) for row in rows]

    def list_reasoning_items_for_question(self, question_id: str) -> List[models.ReasoningItem]:
        rows = self._conn.execute(
            """
            SELECT * FROM reasoning_items
            WHERE question_id = ?
            ORDER BY created_at
            """,
            (question_id,),
        ).fetchall()
        return [self._reasoning_item_from_row(row) for row in rows]

    def _reasoning_item_from_row(self, row: sqlite3.Row) -> models.ReasoningItem:
        return models.ReasoningItem(
            id=row["id"],
            decision_id=row["decision_id"],
            question_id=row["question_id"],
            kind=row["kind"],
            content=row["content"],
            source_type=row["source_type"] if "source_type" in row.keys() and row["source_type"] else "system",
            memory_level=(
                row["memory_level"]
                if "memory_level" in row.keys() and row["memory_level"]
                else "private_context"
            ),
            created_at=_from_iso(row["created_at"]),
        )

    def add_decision(self, decision: models.Decision) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO decisions (
                id, session_id, title, topic, decision_text, rationale,
                background, assumptions, risks, alternatives_considered, consequences, follow_up_notes,
                status, owner, created_at, effective_from, review_date, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.session_id,
                decision.title,
                decision.topic,
                decision.decision_text,
                decision.rationale,
                decision.background,
                decision.assumptions,
                decision.risks,
                decision.alternatives_considered,
                decision.consequences,
                decision.follow_up_notes,
                decision.status,
                decision.owner,
                _to_iso(decision.created_at),
                _to_iso(decision.effective_from) if decision.effective_from else None,
                _to_iso(decision.review_date) if decision.review_date else None,
                json.dumps(decision.tags),
            ),
        )
        self._conn.commit()

    def get_decision(self, decision_id: str) -> Optional[models.Decision]:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if not row:
            return None
        return self._decision_from_row(row)

    def list_decisions_for_session(self, session_id: str) -> List[models.Decision]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def list_active_decisions(self) -> List[models.Decision]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def _decision_from_row(self, row: sqlite3.Row) -> models.Decision:
        return models.Decision(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            topic=row["topic"],
            decision_text=row["decision_text"],
            rationale=row["rationale"],
            background=row["background"] if "background" in row.keys() else None,
            assumptions=row["assumptions"] if "assumptions" in row.keys() else None,
            risks=row["risks"] if "risks" in row.keys() else None,
            alternatives_considered=row["alternatives_considered"] if "alternatives_considered" in row.keys() else None,
            consequences=row["consequences"] if "consequences" in row.keys() else None,
            follow_up_notes=row["follow_up_notes"] if "follow_up_notes" in row.keys() else None,
            status=row["status"],
            owner=row["owner"],
            created_at=_from_iso(row["created_at"]),
            effective_from=_from_iso(row["effective_from"]) if row["effective_from"] else None,
            review_date=_from_iso(row["review_date"]) if row["review_date"] else None,
            tags=json.loads(row["tags"]) if row["tags"] else [],
        )

    def update_decision_status(self, decision_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE decisions SET status = ? WHERE id = ?",
            (status, decision_id),
        )
        self._conn.commit()

    def add_decision_link(self, link: models.DecisionLink) -> None:
        self._conn.execute(
            """
            INSERT INTO decision_links (
                id, from_decision_id, to_decision_id, relation_type, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                link.id,
                link.from_decision_id,
                link.to_decision_id,
                link.relation_type,
                _to_iso(link.created_at),
            ),
        )
        self._conn.commit()

    def get_decision_link(self, link_id: str) -> Optional[models.DecisionLink]:
        row = self._conn.execute(
            "SELECT * FROM decision_links WHERE id = ?",
            (link_id,),
        ).fetchone()
        if not row:
            return None
        return self._decision_link_from_row(row)

    def list_links_for_decision(self, decision_id: str) -> List[models.DecisionLink]:
        rows = self._conn.execute(
            """
            SELECT * FROM decision_links
            WHERE from_decision_id = ? OR to_decision_id = ?
            ORDER BY created_at DESC
            """,
            (decision_id, decision_id),
        ).fetchall()
        return [self._decision_link_from_row(row) for row in rows]

    def list_outgoing_links(self, decision_id: str) -> List[models.DecisionLink]:
        rows = self._conn.execute(
            """
            SELECT * FROM decision_links
            WHERE from_decision_id = ?
            ORDER BY created_at DESC
            """,
            (decision_id,),
        ).fetchall()
        return [self._decision_link_from_row(row) for row in rows]

    def list_incoming_links(self, decision_id: str) -> List[models.DecisionLink]:
        rows = self._conn.execute(
            """
            SELECT * FROM decision_links
            WHERE to_decision_id = ?
            ORDER BY created_at DESC
            """,
            (decision_id,),
        ).fetchall()
        return [self._decision_link_from_row(row) for row in rows]

    def _decision_link_from_row(self, row: sqlite3.Row) -> models.DecisionLink:
        return models.DecisionLink(
            id=row["id"],
            from_decision_id=row["from_decision_id"],
            to_decision_id=row["to_decision_id"],
            relation_type=row["relation_type"],
            created_at=_from_iso(row["created_at"]),
        )

    def add_decision_suggestion(self, suggestion: models.DecisionSuggestion) -> None:
        self._conn.execute(
            """
            INSERT INTO decision_suggestions (
                id, source_decision_id, target_decision_id, suggestion_type, reason, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion.id,
                suggestion.source_decision_id,
                suggestion.target_decision_id,
                suggestion.suggestion_type,
                suggestion.reason,
                suggestion.status,
                _to_iso(suggestion.created_at),
            ),
        )
        self._conn.commit()

    def get_decision_suggestion(self, suggestion_id: str) -> Optional[models.DecisionSuggestion]:
        row = self._conn.execute(
            "SELECT * FROM decision_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        if not row:
            return None
        return self._decision_suggestion_from_row(row)

    def update_decision_suggestion_status(self, suggestion_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE decision_suggestions SET status = ? WHERE id = ?",
            (status, suggestion_id),
        )
        self._conn.commit()

    def list_suggestions_for_decision(self, decision_id: str) -> List[models.DecisionSuggestion]:
        rows = self._conn.execute(
            """
            SELECT * FROM decision_suggestions
            WHERE source_decision_id = ? OR target_decision_id = ?
            ORDER BY created_at DESC
            """,
            (decision_id, decision_id),
        ).fetchall()
        return [self._decision_suggestion_from_row(row) for row in rows]

    def list_open_suggestions(self) -> List[models.DecisionSuggestion]:
        rows = self._conn.execute(
            "SELECT * FROM decision_suggestions WHERE status = 'open' ORDER BY created_at DESC"
        ).fetchall()
        return [self._decision_suggestion_from_row(row) for row in rows]

    def list_open_decision_suggestions(self) -> List[models.DecisionSuggestion]:
        return self.list_open_suggestions()

    def _decision_suggestion_from_row(self, row: sqlite3.Row) -> models.DecisionSuggestion:
        return models.DecisionSuggestion(
            id=row["id"],
            source_decision_id=row["source_decision_id"],
            target_decision_id=row["target_decision_id"],
            suggestion_type=row["suggestion_type"],
            reason=row["reason"],
            status=row["status"],
            created_at=_from_iso(row["created_at"]),
        )

    def add_panel_question(self, question: models.ExecutiveQuestion) -> None:
        workspace_id = question.workspace_id
        if workspace_id is None and question.session_id:
            session = self.get_session(question.session_id)
            if session is not None:
                workspace_id = session.workspace_id
        if workspace_id is None:
            workspace_id = self.get_active_workspace().id
        self._conn.execute(
            """
            INSERT OR REPLACE INTO panel_questions (
                id, question, question_text, topic, session_id, workspace_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question.id,
                question.question_text,
                question.question_text,
                question.topic,
                question.session_id,
                workspace_id,
                question.status,
                _to_iso(question.created_at),
            ),
        )
        self._conn.commit()

    def get_panel_question(self, question_id: str) -> Optional[models.ExecutiveQuestion]:
        row = self._conn.execute(
            "SELECT * FROM panel_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not row:
            return None
        return self._panel_question_from_row(row)

    def list_panel_questions(
        self,
        session_id: str | None = None,
        workspace_id: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> List[models.ExecutiveQuestion]:
        query = "SELECT * FROM panel_questions"
        conditions: List[str] = []
        params: List[object] = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if topic:
            conditions.append("topic = ?")
            params.append(topic)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._panel_question_from_row(row) for row in rows]

    def _panel_question_from_row(self, row: sqlite3.Row) -> models.ExecutiveQuestion:
        question_text = row["question_text"] if "question_text" in row.keys() and row["question_text"] else row["question"]
        return models.ExecutiveQuestion(
            id=row["id"],
            question_text=question_text,
            topic=row["topic"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"] if "workspace_id" in row.keys() else None,
            status=row["status"] if "status" in row.keys() and row["status"] else "open",
            created_at=_from_iso(row["created_at"]),
        )

    def add_panel_responses(self, responses: Iterable[models.PanelResponse]) -> None:
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO panel_responses (
                id, question_id, agent_name, response_text, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    response.id,
                    response.question_id,
                    response.agent_name,
                    response.response_text,
                    _to_iso(response.created_at),
                )
                for response in responses
            ],
        )
        self._conn.commit()

    def list_panel_responses(self, question_id: str) -> List[models.PanelResponse]:
        rows = self._conn.execute(
            "SELECT * FROM panel_responses WHERE question_id = ? ORDER BY created_at",
            (question_id,),
        ).fetchall()
        return [
            models.PanelResponse(
                id=row["id"],
                question_id=row["question_id"],
                agent_name=row["agent_name"],
                response_text=row["response_text"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def add_panel_question_analysis(self, analysis: models.ExecutiveQuestionAnalysis) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO panel_question_analyses (
                id,
                question_id,
                assessment_alignment,
                assessment_reason,
                challenge_points,
                question_interpretation,
                relevant_context,
                per_role_analysis,
                tensions,
                combined_recommendation,
                suggested_next_step,
                likely_requires_new_decision,
                decision_status_assessment,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.id,
                analysis.question_id,
                analysis.assessment_alignment,
                analysis.assessment_reason,
                json.dumps(analysis.challenge_points),
                analysis.question_interpretation,
                json.dumps(analysis.relevant_context),
                json.dumps(analysis.per_role_analysis),
                json.dumps(analysis.tensions),
                analysis.combined_recommendation,
                analysis.suggested_next_step,
                analysis.likely_requires_new_decision,
                json.dumps(analysis.decision_status_assessment),
                _to_iso(analysis.created_at),
            ),
        )
        self._conn.commit()

    def get_panel_question_analysis(self, question_id: str) -> Optional[models.ExecutiveQuestionAnalysis]:
        row = self._conn.execute(
            "SELECT * FROM panel_question_analyses WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if not row:
            return None
        return models.ExecutiveQuestionAnalysis(
            id=row["id"],
            question_id=row["question_id"],
            assessment_alignment=row["assessment_alignment"],
            assessment_reason=row["assessment_reason"],
            challenge_points=json.loads(row["challenge_points"]) if row["challenge_points"] else [],
            question_interpretation=row["question_interpretation"] if "question_interpretation" in row.keys() else None,
            relevant_context=json.loads(row["relevant_context"])
            if "relevant_context" in row.keys() and row["relevant_context"]
            else {},
            per_role_analysis=json.loads(row["per_role_analysis"])
            if "per_role_analysis" in row.keys() and row["per_role_analysis"]
            else {},
            tensions=json.loads(row["tensions"]) if "tensions" in row.keys() and row["tensions"] else [],
            combined_recommendation=row["combined_recommendation"],
            suggested_next_step=row["suggested_next_step"],
            likely_requires_new_decision=row["likely_requires_new_decision"],
            decision_status_assessment=json.loads(row["decision_status_assessment"])
            if "decision_status_assessment" in row.keys() and row["decision_status_assessment"]
            else {},
            created_at=_from_iso(row["created_at"]),
        )

    def set_panel_question_context_decisions(self, question_id: str, decision_ids: List[str]) -> None:
        self._conn.execute(
            "DELETE FROM panel_question_context_decisions WHERE question_id = ?",
            (question_id,),
        )
        if decision_ids:
            self._conn.executemany(
                """
                INSERT INTO panel_question_context_decisions (question_id, decision_id)
                VALUES (?, ?)
                """,
                [(question_id, decision_id) for decision_id in decision_ids],
            )
        self._conn.commit()

    def list_panel_question_context_decision_ids(self, question_id: str) -> List[str]:
        rows = self._conn.execute(
            """
            SELECT decision_id
            FROM panel_question_context_decisions
            WHERE question_id = ?
            ORDER BY decision_id
            """,
            (question_id,),
        ).fetchall()
        return [row["decision_id"] for row in rows]

    def get_panel_question_case(self, question_id: str) -> Optional[dict]:
        question = self.get_panel_question(question_id)
        if question is None:
            return None
        return {
            "question": question,
            "analysis": self.get_panel_question_analysis(question_id),
            "context_decision_ids": self.list_panel_question_context_decision_ids(question_id),
            "responses": self.list_panel_responses(question_id),
            "sections": self.get_panel_question_sections(question_id),
            "reasoning_items": self.list_reasoning_items_for_question(question_id),
        }

    def get_panel_question_sections(self, question_id: str) -> dict:
        analysis = self.get_panel_question_analysis(question_id)
        if analysis is None:
            return {}
        return {
            "question_interpretation": analysis.question_interpretation,
            "relevant_context": analysis.relevant_context,
            "per_role_analysis": analysis.per_role_analysis,
            "tensions": analysis.tensions,
            "combined_recommendation": analysis.combined_recommendation,
            "decision_status_assessment": analysis.decision_status_assessment,
        }

    def add_decision_candidate(self, candidate: models.DecisionCandidate) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO decision_candidates (
                id, session_id, title, topic, candidate_text, rationale, status, owner, created_at, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.id,
                candidate.session_id,
                candidate.title,
                candidate.topic,
                candidate.candidate_text,
                candidate.rationale,
                candidate.status,
                candidate.owner,
                _to_iso(candidate.created_at),
                json.dumps(candidate.tags),
            ),
        )
        self._conn.commit()

    def get_decision_candidate(self, candidate_id: str) -> Optional[models.DecisionCandidate]:
        row = self._conn.execute(
            "SELECT * FROM decision_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if not row:
            return None
        return self._decision_candidate_from_row(row)

    def update_decision_candidate_status(self, candidate_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE decision_candidates SET status = ? WHERE id = ?",
            (status, candidate_id),
        )
        self._conn.commit()

    def list_decision_candidates_for_session(self, session_id: str) -> List[models.DecisionCandidate]:
        rows = self._conn.execute(
            "SELECT * FROM decision_candidates WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [self._decision_candidate_from_row(row) for row in rows]

    def list_open_decision_candidates(self) -> List[models.DecisionCandidate]:
        rows = self._conn.execute(
            "SELECT * FROM decision_candidates WHERE status = 'proposed' ORDER BY created_at DESC"
        ).fetchall()
        return [self._decision_candidate_from_row(row) for row in rows]

    def _decision_candidate_from_row(self, row: sqlite3.Row) -> models.DecisionCandidate:
        return models.DecisionCandidate(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            topic=row["topic"],
            candidate_text=row["candidate_text"],
            rationale=row["rationale"],
            status=row["status"],
            owner=row["owner"],
            created_at=_from_iso(row["created_at"]),
            tags=json.loads(row["tags"]) if row["tags"] else [],
        )

    def list_session_events(self, session_id: str) -> List[models.SessionEvent]:
        rows = self._conn.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [
            models.SessionEvent(
                id=row["id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                message=row["message"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def list_recent_session_events(self, limit: int = 10) -> List[models.SessionEvent]:
        rows = self._conn.execute(
            "SELECT * FROM session_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            models.SessionEvent(
                id=row["id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                message=row["message"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def list_session_history(self, session_id: str) -> List[dict]:
        history: List[dict] = []
        for event in self.list_session_events(session_id):
            history.append(
                {
                    "created_at": event.created_at,
                    "source": "event",
                    "kind": event.event_type,
                    "message": event.message,
                }
            )
        for action in self.list_agent_actions_for_session(session_id):
            history.append(
                {
                    "created_at": action.created_at,
                    "source": "agent_action",
                    "kind": action.kind,
                    "message": f"{action.agent_name}: {action.content}",
                }
            )
        for memory in self.list_memory_items(session_id):
            history.append(
                {
                    "created_at": memory.created_at,
                    "source": "memory",
                    "kind": memory.kind,
                    "message": memory.content,
                }
            )
        history.sort(key=lambda item: item["created_at"])
        return history

    def list_memory_items(self, session_id: str) -> List[models.MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memory_items WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def list_memory_for_task(self, task_id: str) -> List[models.MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memory_items WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def _memory_from_row(self, row: sqlite3.Row) -> models.MemoryItem:
        return models.MemoryItem(
            id=row["id"],
            session_id=row["session_id"],
            scope=row["scope"],
            kind=row["kind"],
            source_agent=row["source_agent"],
            task_id=row["task_id"],
            content=row["content"],
            created_at=_from_iso(row["created_at"]),
        )

    def close(self) -> None:
        self._conn.close()
