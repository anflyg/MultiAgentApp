from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from . import models


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
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
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
            """
        )
        self._ensure_column("sessions", "status", "TEXT NOT NULL DEFAULT 'active'")
        self._ensure_column("tasks", "priority", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("tasks", "owner_agent", "TEXT")
        self._ensure_column("agent_actions", "session_id", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("agent_actions", "kind", "TEXT NOT NULL DEFAULT 'result'")
        self._ensure_column("memory_items", "scope", "TEXT NOT NULL DEFAULT 'session'")
        self._ensure_column("memory_items", "kind", "TEXT NOT NULL DEFAULT 'fact'")
        self._ensure_column("memory_items", "source_agent", "TEXT")
        self._ensure_column("memory_items", "task_id", "TEXT")
        self._conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_columns = {row["name"] for row in rows}
        if column not in existing_columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_session(self, session: models.Session) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (id, name, status, created_at) VALUES (?, ?, ?, ?)",
            (session.id, session.name, session.status, _to_iso(session.created_at)),
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
            status=row["status"],
            created_at=_from_iso(row["created_at"]),
        )

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
