from __future__ import annotations

import argparse
from typing import Dict, List

from . import models
from .orchestrator import Orchestrator
from .storage import Storage


def _default_agents() -> Dict[str, callable]:
    return {
        "writer": lambda task: f"Drafted text for: {task.description}",
        "reviewer": lambda task: f"Reviewed task '{task.description}' with no issues found.",
        "planner": lambda task: f"Planned next steps for: {task.description}",
    }


def run_example_flow(
    db_path: str = "multi_agent.db",
    session_name: str = "Demo Session",
    task_description: str = "Write a welcome message",
    agent_name: str = "writer",
) -> Dict[str, object]:
    storage = Storage(db_path=db_path)
    orchestrator = Orchestrator(storage, agents=_default_agents())

    session = orchestrator.create_session(session_name)
    task = orchestrator.create_task(session.id, task_description)
    action = orchestrator.route_task(task, agent_name)
    memory_items: List[models.MemoryItem] = storage.list_memory_items(session.id)

    storage.close()
    return {
        "session": session,
        "task": task,
        "action": action,
        "memory_items": memory_items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a demo multi-agent workflow.")
    parser.add_argument("--db-path", default="multi_agent.db", help="Path to SQLite database file.")
    parser.add_argument("--session-name", default="Demo Session", help="Session name.")
    parser.add_argument("--task", dest="task_description", default="Write a welcome message", help="Task description.")
    parser.add_argument("--agent", dest="agent_name", default="writer", help="Agent to route the task to.")
    args = parser.parse_args()

    result = run_example_flow(
        db_path=args.db_path,
        session_name=args.session_name,
        task_description=args.task_description,
        agent_name=args.agent_name,
    )

    print(f"Session: {result['session'].id} ({result['session'].name})")
    print(f"Task: {result['task'].description} -> status {result['task'].status}")
    print(f"Agent '{result['action'].agent_name}' output: {result['action'].content}")
    print(f"Stored {len(result['memory_items'])} memory item(s).")


if __name__ == "__main__":
    main()
