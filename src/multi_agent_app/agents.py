from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Task


class BaseAgent(ABC):
    name = "base"

    @abstractmethod
    def run(self, task: Task) -> str:
        """Execute work for a task and return a result string."""


class WriterAgent(BaseAgent):
    name = "writer"

    def run(self, task: Task) -> str:
        return f"Drafted text for: {task.description}"


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def run(self, task: Task) -> str:
        return f"Reviewed task '{task.description}' with no issues found."


class PlannerAgent(BaseAgent):
    name = "planner"

    def run(self, task: Task) -> str:
        return f"Planned next steps for: {task.description}"
