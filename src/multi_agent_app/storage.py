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
    """Simple SQLite-backed persistence layer."""

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
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS agent_actions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            """
        )
        self._conn.commit()

    def add_session(self, session: models.Session) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (id, name, created_at) VALUES (?, ?, ?)",
            (session.id, session.name, _to_iso(session.created_at)),
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
            created_at=_from_iso(row["created_at"]),
        )

    def add_task(self, task: models.Task) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO tasks (id, session_id, description, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task.id, task.session_id, task.description, task.status, _to_iso(task.created_at)),
        )
        self._conn.commit()

    def update_task_status(self, task_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        self._conn.commit()

    def list_tasks(self, session_id: str) -> List[models.Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [
            models.Task(
                id=row["id"],
                session_id=row["session_id"],
                description=row["description"],
                status=row["status"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def add_agent_action(self, action: models.AgentAction) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO agent_actions (id, task_id, agent_name, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action.id, action.task_id, action.agent_name, action.content, _to_iso(action.created_at)),
        )
        self._conn.commit()

    def list_agent_actions(self, task_id: str) -> List[models.AgentAction]:
        rows = self._conn.execute(
            "SELECT * FROM agent_actions WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [
            models.AgentAction(
                id=row["id"],
                task_id=row["task_id"],
                agent_name=row["agent_name"],
                content=row["content"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def add_memory_items(self, items: Iterable[models.MemoryItem]) -> None:
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO memory_items (id, session_id, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (item.id, item.session_id, item.content, _to_iso(item.created_at))
                for item in items
            ],
        )
        self._conn.commit()

    def list_memory_items(self, session_id: str) -> List[models.MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memory_items WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [
            models.MemoryItem(
                id=row["id"],
                session_id=row["session_id"],
                content=row["content"],
                created_at=_from_iso(row["created_at"]),
            )
            for row in rows
        ]

    def close(self) -> None:
        self._conn.close()
