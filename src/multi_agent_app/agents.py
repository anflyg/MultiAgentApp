from __future__ import annotations

from .models import Task


class BaseAgent:
    name = "base"

    def run(self, task: Task) -> str:
        raise NotImplementedError("Agents must implement run(task)")


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
