from __future__ import annotations

from typing import Dict, Mapping, Protocol

from . import models
from .storage import Storage


class AgentProtocol(Protocol):
    def run(self, task: models.Task) -> str:
        ...


class OrchestrationError(RuntimeError):
    """Raised when a routed task fails inside an agent."""


class Orchestrator:
    """Routes tasks to named agents and records their actions."""

    def __init__(self, storage: Storage, agents: Mapping[str, AgentProtocol] | None = None) -> None:
        self.storage = storage
        self.agents: Dict[str, AgentProtocol] = dict(agents or {})

    def register_agent(self, name: str, agent: AgentProtocol) -> None:
        self.agents[name] = agent

    def create_session(self, name: str) -> models.Session:
        session = models.Session(name=name)
        self.storage.add_session(session)
        return session

    def create_task(self, session_id: str, description: str, priority: int = 0) -> models.Task:
        task = models.Task(session_id=session_id, description=description, priority=priority)
        self.storage.add_task(task)
        return task

    def route_task(self, task: models.Task, agent_name: str) -> models.AgentAction:
        if agent_name not in self.agents:
            raise KeyError(f"Agent '{agent_name}' is not registered")

        agent = self.agents[agent_name]
        task.owner_agent = agent_name
        task.status = "in_progress"
        self.storage.update_task_owner(task.id, agent_name)
        self.storage.update_task_status(task.id, "in_progress")

        try:
            content = agent.run(task)
            action = models.AgentAction(
                session_id=task.session_id,
                task_id=task.id,
                agent_name=agent_name,
                kind="result",
                content=content,
            )
            self.storage.add_agent_action(action)

            memory_item = models.MemoryItem(
                session_id=task.session_id,
                scope="session",
                kind="summary",
                source_agent=agent_name,
                task_id=task.id,
                content=content,
            )
            self.storage.add_memory_items([memory_item])

            task.status = "completed"
            self.storage.update_task_status(task.id, "completed")
            return action
        except Exception as exc:
            task.status = "failed"
            self.storage.update_task_status(task.id, "failed")
            self.storage.add_agent_action(
                models.AgentAction(
                    session_id=task.session_id,
                    task_id=task.id,
                    agent_name=agent_name,
                    kind="error",
                    content=str(exc),
                )
            )
            raise OrchestrationError(
                f"Task '{task.id}' failed in agent '{agent_name}': {exc}"
            ) from exc
