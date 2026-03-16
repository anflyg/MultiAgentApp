from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    status: Literal["active", "completed", "failed"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    description: str
    priority: int = 0
    owner_agent: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str
    agent_name: str
    kind: Literal["result", "error", "system"] = "result"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    scope: Literal["session", "project", "user"] = "session"
    kind: Literal["fact", "decision", "preference", "summary", "open_question"] = "fact"
    source_agent: str | None = None
    task_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
