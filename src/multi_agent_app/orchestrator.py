from __future__ import annotations

from typing import Dict, Literal, Mapping

from . import models
from .agents import BaseAgent
from .storage import Storage


class OrchestrationError(RuntimeError):
    """Raised when a routed task fails inside an agent."""


class Orchestrator:
    """Routes tasks to named agents and records their actions."""

    def __init__(self, storage: Storage, agents: Mapping[str, BaseAgent] | None = None) -> None:
        self.storage = storage
        self.agents: Dict[str, BaseAgent] = dict(agents or {})

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        self.agents[name] = agent

    def create_session(self, name: str) -> models.Session:
        session = models.Session(name=name)
        self.storage.add_session(session)
        self.storage.add_session_event(
            models.SessionEvent(
                session_id=session.id,
                event_type="session_created",
                message=f"Session '{session.name}' created",
            )
        )
        return session

    def create_task(self, session_id: str, description: str, priority: int = 0) -> models.Task:
        task = models.Task(session_id=session_id, description=description, priority=priority)
        self.storage.add_task(task)
        self.storage.add_session_event(
            models.SessionEvent(
                session_id=session_id,
                event_type="task_created",
                message=f"Task '{task.id}' created",
            )
        )
        self._set_session_status(session_id, "active")
        return task

    def _set_session_status(
        self, session_id: str, status: Literal["active", "completed", "failed"]
    ) -> None:
        current = self.storage.get_session(session_id)
        if current is None or current.status == status:
            return
        self.storage.update_session_status(session_id, status)
        self.storage.add_session_event(
            models.SessionEvent(
                session_id=session_id,
                event_type="session_status_changed",
                message=f"Session status changed: {current.status} -> {status}",
            )
        )

    def _refresh_session_status(self, session_id: str) -> None:
        tasks = self.storage.list_tasks(session_id)
        if not tasks:
            self._set_session_status(session_id, "active")
            return
        if any(task.status == "failed" for task in tasks):
            self._set_session_status(session_id, "failed")
            return
        if all(task.status == "completed" for task in tasks):
            self._set_session_status(session_id, "completed")
            return
        self._set_session_status(session_id, "active")

    def route_task(self, task: models.Task, agent_name: str) -> models.AgentAction:
        if agent_name not in self.agents:
            raise KeyError(f"Agent '{agent_name}' is not registered")

        agent = self.agents[agent_name]
        task.owner_agent = agent_name
        task.status = "in_progress"
        self.storage.update_task_owner(task.id, agent_name)
        self.storage.update_task_status(task.id, "in_progress")
        self.storage.add_session_event(
            models.SessionEvent(
                session_id=task.session_id,
                event_type="task_routed",
                message=f"Task '{task.id}' routed to '{agent_name}'",
            )
        )

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
            self.storage.add_session_event(
                models.SessionEvent(
                    session_id=task.session_id,
                    event_type="memory_created",
                    message=f"Memory captured for task '{task.id}' from '{agent_name}'",
                )
            )

            task.status = "completed"
            self.storage.update_task_status(task.id, "completed")
            self.storage.add_session_event(
                models.SessionEvent(
                    session_id=task.session_id,
                    event_type="task_completed",
                    message=f"Task '{task.id}' completed by '{agent_name}'",
                )
            )
            self._refresh_session_status(task.session_id)
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
            self.storage.add_session_event(
                models.SessionEvent(
                    session_id=task.session_id,
                    event_type="task_failed",
                    message=f"Task '{task.id}' failed in '{agent_name}': {exc}",
                )
            )
            self._refresh_session_status(task.session_id)
            raise OrchestrationError(
                f"Task '{task.id}' failed in agent '{agent_name}': {exc}"
            ) from exc
