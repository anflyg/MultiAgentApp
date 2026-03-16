from __future__ import annotations

import argparse
from typing import Dict, List

from . import models
from .agents import BaseAgent, PlannerAgent, ReviewerAgent, WriterAgent
from .orchestrator import OrchestrationError, Orchestrator
from .storage import Storage


def _default_agents() -> Dict[str, BaseAgent]:
    return {
        "writer": WriterAgent(),
        "reviewer": ReviewerAgent(),
        "planner": PlannerAgent(),
    }


def run_example_flow(
    db_path: str = "multi_agent.db",
    session_name: str = "Demo Session",
    task_description: str = "Write a welcome message",
    agent_name: str = "writer",
) -> Dict[str, object]:
    storage = Storage(db_path=db_path)
    orchestrator = Orchestrator(storage, agents=_default_agents())
    try:
        session = orchestrator.create_session(session_name)
        task = orchestrator.create_task(session.id, task_description)
        action = orchestrator.route_task(task, agent_name)
        saved_task = storage.get_task(task.id)
        memory_items: List[models.MemoryItem] = storage.list_memory_for_task(task.id)

        return {
            "session": session,
            "task": saved_task or task,
            "action": action,
            "memory_items": memory_items,
        }
    finally:
        storage.close()


def list_memory_for_session(db_path: str, session_id: str) -> List[models.MemoryItem]:
    storage = Storage(db_path=db_path)
    try:
        return storage.list_memory_items(session_id)
    finally:
        storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a demo multi-agent workflow.")
    parser.add_argument("--db-path", default="multi_agent.db", help="Path to SQLite database file.")
    parser.add_argument("--session-name", default="Demo Session", help="Session name.")
    parser.add_argument("--task", dest="task_description", default="Write a welcome message", help="Task description.")
    parser.add_argument("--agent", dest="agent_name", default="writer", help="Agent to route the task to.")
    parser.add_argument(
        "--list-memory",
        dest="list_memory_session_id",
        help="List memory items for an existing session id and exit.",
    )
    args = parser.parse_args()

    if args.list_memory_session_id:
        memory_items = list_memory_for_session(args.db_path, args.list_memory_session_id)
        print(f"Session {args.list_memory_session_id}: {len(memory_items)} memory item(s)")
        for item in memory_items:
            print(f"- {item.id} [{item.kind}/{item.scope}] agent={item.source_agent} task={item.task_id}")
            print(f"  {item.content}")
        return

    try:
        result = run_example_flow(
            db_path=args.db_path,
            session_name=args.session_name,
            task_description=args.task_description,
            agent_name=args.agent_name,
        )
    except OrchestrationError as exc:
        print(f"Workflow failed: {exc}")
        raise SystemExit(1) from exc

    print(f"Session ID: {result['session'].id}")
    print(f"Task ID: {result['task'].id}")
    print(f"Task status: {result['task'].status}")
    print(f"Agent used: {result['action'].agent_name}")
    print(f"Action kind: {result['action'].kind}")
    print(f"Agent output: {result['action'].content}")
    print(f"Memory items created: {len(result['memory_items'])}")


if __name__ == "__main__":
    main()
