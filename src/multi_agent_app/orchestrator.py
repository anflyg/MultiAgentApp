from __future__ import annotations

from typing import Callable, Dict, Mapping

from . import models
from .storage import Storage


AgentHandler = Callable[[models.Task], str]


class Orchestrator:
    """Routes tasks to named agents and records their actions."""

    def __init__(self, storage: Storage, agents: Mapping[str, AgentHandler] | None = None) -> None:
        self.storage = storage
        self.agents: Dict[str, AgentHandler] = dict(agents or {})

    def register_agent(self, name: str, handler: AgentHandler) -> None:
        self.agents[name] = handler

    def create_session(self, name: str) -> models.Session:
        session = models.Session(name=name)
        self.storage.add_session(session)
        return session

    def create_task(self, session_id: str, description: str) -> models.Task:
        task = models.Task(session_id=session_id, description=description, status="pending")
        self.storage.add_task(task)
        return task

    def route_task(self, task: models.Task, agent_name: str) -> models.AgentAction:
        if agent_name not in self.agents:
            raise KeyError(f"Agent '{agent_name}' is not registered")

        handler = self.agents[agent_name]
        self.storage.update_task_status(task.id, "in_progress")
        content = handler(task)
        action = models.AgentAction(task_id=task.id, agent_name=agent_name, content=content)
        self.storage.add_agent_action(action)
        memory_item = models.MemoryItem(session_id=task.session_id, content=content)
        self.storage.add_memory_items([memory_item])
        self.storage.update_task_status(task.id, "completed")
        return action
