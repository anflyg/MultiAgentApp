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


def create_session(db_path: str, session_name: str) -> models.Session:
    storage = Storage(db_path=db_path)
    orchestrator = Orchestrator(storage, agents=_default_agents())
    try:
        return orchestrator.create_session(session_name)
    finally:
        storage.close()


def add_task_to_session(
    db_path: str, session_id: str, task_description: str, priority: int = 0
) -> models.Task:
    storage = Storage(db_path=db_path)
    orchestrator = Orchestrator(storage, agents=_default_agents())
    try:
        return orchestrator.create_task(session_id, task_description, priority=priority)
    finally:
        storage.close()


def list_tasks_for_session(db_path: str, session_id: str) -> List[models.Task]:
    storage = Storage(db_path=db_path)
    try:
        return storage.list_tasks(session_id)
    finally:
        storage.close()


def route_task_by_id(db_path: str, task_id: str, agent_name: str) -> models.AgentAction:
    storage = Storage(db_path=db_path)
    orchestrator = Orchestrator(storage, agents=_default_agents())
    try:
        task = storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' was not found")
        return orchestrator.route_task(task, agent_name)
    finally:
        storage.close()


def get_session_status(db_path: str, session_id: str) -> str:
    storage = Storage(db_path=db_path)
    try:
        session = storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' was not found")
        return session.status
    finally:
        storage.close()


def get_session_summary(db_path: str, session_id: str) -> Dict[str, object]:
    storage = Storage(db_path=db_path)
    try:
        session = storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' was not found")
        tasks = storage.list_tasks(session_id)
        history = storage.list_session_history(session_id)
        return {"session": session, "tasks": tasks, "history": history}
    finally:
        storage.close()


def list_memory_for_session(db_path: str, session_id: str) -> List[models.MemoryItem]:
    storage = Storage(db_path=db_path)
    try:
        return storage.list_memory_items(session_id)
    finally:
        storage.close()


def list_history_for_session(db_path: str, session_id: str) -> List[dict]:
    storage = Storage(db_path=db_path)
    try:
        return storage.list_session_history(session_id)
    finally:
        storage.close()


def create_decision(
    db_path: str,
    session_id: str,
    title: str,
    topic: str,
    decision_text: str,
    rationale: str | None = None,
    owner: str | None = None,
    tags: List[str] | None = None,
) -> models.Decision:
    storage = Storage(db_path=db_path)
    try:
        session = storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' was not found")
        decision = models.Decision(
            session_id=session_id,
            title=title,
            topic=topic,
            decision_text=decision_text,
            rationale=rationale,
            owner=owner,
            tags=tags or [],
        )
        storage.add_decision(decision)
        storage.add_session_event(
            models.SessionEvent(
                session_id=session_id,
                event_type="decision_created",
                message=f"Decision '{decision.id}' created: {decision.title}",
            )
        )
        return decision
    finally:
        storage.close()


def list_decisions(db_path: str, session_id: str | None = None) -> List[models.Decision]:
    storage = Storage(db_path=db_path)
    try:
        if session_id:
            session = storage.get_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' was not found")
            return storage.list_decisions_for_session(session_id)
        return storage.list_active_decisions()
    finally:
        storage.close()


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
        saved_session = storage.get_session(session.id)
        saved_task = storage.get_task(task.id)
        memory_items: List[models.MemoryItem] = storage.list_memory_for_task(task.id)
        return {
            "session": saved_session or session,
            "task": saved_task or task,
            "action": action,
            "memory_items": memory_items,
        }
    finally:
        storage.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MultiAgentApp CLI.")
    parser.add_argument("--db-path", default="multi_agent.db", help="Path to SQLite database file.")
    parser.add_argument("--session-name", default="Demo Session", help="Session name for demo flow.")
    parser.add_argument(
        "--task", dest="task_description", default="Write a welcome message", help="Task description for demo flow."
    )
    parser.add_argument("--agent", dest="agent_name", default="writer", help="Agent for demo flow.")

    subparsers = parser.add_subparsers(dest="command")

    create_session_parser = subparsers.add_parser("create-session", help="Create a new session.")
    create_session_parser.add_argument("--name", required=True, help="Name for the new session.")

    add_task_parser = subparsers.add_parser("add-task", help="Add a task to an existing session.")
    add_task_parser.add_argument("--session-id", required=True, help="Target session id.")
    add_task_parser.add_argument("--description", required=True, help="Task description.")
    add_task_parser.add_argument("--priority", type=int, default=0, help="Task priority.")

    list_tasks_parser = subparsers.add_parser("list-tasks", help="List tasks for a session.")
    list_tasks_parser.add_argument("--session-id", required=True, help="Session id.")

    route_task_parser = subparsers.add_parser("route-task", help="Route a specific task to an agent.")
    route_task_parser.add_argument("--task-id", required=True, help="Task id.")
    route_task_parser.add_argument("--agent", required=True, help="Agent name.")

    run_task_parser = subparsers.add_parser("run-task", help="Run a specific task with a named agent.")
    run_task_parser.add_argument("--task-id", required=True, help="Task id.")
    run_task_parser.add_argument("--agent", required=True, help="Agent name.")

    status_parser = subparsers.add_parser("session-status", help="Show session status.")
    status_parser.add_argument("--session-id", required=True, help="Session id.")

    show_session_parser = subparsers.add_parser("show-session", help="Show session details, tasks and history.")
    show_session_parser.add_argument("--session-id", required=True, help="Session id.")

    memory_parser = subparsers.add_parser("list-memory", help="List memory items for a session.")
    memory_parser.add_argument("--session-id", required=True, help="Session id.")

    history_parser = subparsers.add_parser("session-history", help="Show session-level audit history.")
    history_parser.add_argument("--session-id", required=True, help="Session id.")

    create_decision_parser = subparsers.add_parser("create-decision", help="Create a decision for a session.")
    create_decision_parser.add_argument("--session-id", required=True, help="Session id.")
    create_decision_parser.add_argument("--title", required=True, help="Decision title.")
    create_decision_parser.add_argument("--topic", required=True, help="Decision topic.")
    create_decision_parser.add_argument("--text", dest="decision_text", required=True, help="Decision text.")
    create_decision_parser.add_argument("--rationale", help="Optional rationale.")
    create_decision_parser.add_argument("--owner", help="Optional owner.")
    create_decision_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Decision tag. Repeat --tag for multiple values.",
    )

    list_decisions_parser = subparsers.add_parser("list-decisions", help="List decisions.")
    list_decisions_parser.add_argument("--session-id", help="Optional session id.")

    subparsers.add_parser("tui", help="Launch Textual terminal UI.")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "create-session":
        session = create_session(args.db_path, args.name)
        print(f"Created session: {session.id} ({session.name}) status={session.status}")
        return

    if args.command == "add-task":
        task = add_task_to_session(args.db_path, args.session_id, args.description, priority=args.priority)
        print(f"Added task: {task.id} status={task.status} priority={task.priority}")
        return

    if args.command == "list-tasks":
        tasks = list_tasks_for_session(args.db_path, args.session_id)
        print(f"Session {args.session_id}: {len(tasks)} task(s)")
        for task in tasks:
            print(f"- {task.id} [{task.status}] owner={task.owner_agent} priority={task.priority}")
            print(f"  {task.description}")
        return

    if args.command == "route-task":
        try:
            action = route_task_by_id(args.db_path, args.task_id, args.agent)
        except OrchestrationError as exc:
            print(f"Routing failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Routed task {action.task_id} with agent {action.agent_name} kind={action.kind}")
        print(action.content)
        return

    if args.command == "run-task":
        try:
            action = route_task_by_id(args.db_path, args.task_id, args.agent)
        except OrchestrationError as exc:
            print(f"Routing failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Ran task {action.task_id} with agent {action.agent_name} kind={action.kind}")
        print(action.content)
        return

    if args.command == "session-status":
        status = get_session_status(args.db_path, args.session_id)
        print(f"Session {args.session_id} status: {status}")
        return

    if args.command == "show-session":
        summary = get_session_summary(args.db_path, args.session_id)
        session = summary["session"]
        tasks = summary["tasks"]
        history = summary["history"]
        print(f"Session {session.id}: name={session.name} status={session.status}")
        print(f"Tasks: {len(tasks)}")
        for task in tasks:
            print(f"- {task.id} [{task.status}] owner={task.owner_agent} priority={task.priority}")
            print(f"  {task.description}")
        print(f"History: {len(history)}")
        for item in history:
            print(f"- {item['created_at'].isoformat()} [{item['source']}/{item['kind']}] {item['message']}")
        return

    if args.command == "list-memory":
        memory_items = list_memory_for_session(args.db_path, args.session_id)
        print(f"Session {args.session_id}: {len(memory_items)} memory item(s)")
        for item in memory_items:
            print(f"- {item.id} [{item.kind}/{item.scope}] agent={item.source_agent} task={item.task_id}")
            print(f"  {item.content}")
        return

    if args.command == "session-history":
        history = list_history_for_session(args.db_path, args.session_id)
        print(f"Session {args.session_id}: {len(history)} history event(s)")
        for item in history:
            print(f"- {item['created_at'].isoformat()} [{item['source']}/{item['kind']}] {item['message']}")
        return

    if args.command == "create-decision":
        try:
            decision = create_decision(
                db_path=args.db_path,
                session_id=args.session_id,
                title=args.title,
                topic=args.topic,
                decision_text=args.decision_text,
                rationale=args.rationale,
                owner=args.owner,
                tags=args.tags,
            )
        except ValueError as exc:
            print(f"Decision creation failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Created decision: {decision.id}")
        print(f"Session: {decision.session_id}")
        print(f"Title: {decision.title}")
        print(f"Topic: {decision.topic}")
        print(f"Status: {decision.status}")
        print(f"Tags: {', '.join(decision.tags) if decision.tags else '-'}")
        return

    if args.command == "list-decisions":
        try:
            decisions = list_decisions(args.db_path, session_id=args.session_id)
        except ValueError as exc:
            print(f"Decision listing failed: {exc}")
            raise SystemExit(1) from exc
        scope = args.session_id if args.session_id else "all active"
        print(f"Decisions ({scope}): {len(decisions)}")
        for decision in decisions:
            print(
                f"- {decision.id} [{decision.status}] session={decision.session_id} topic={decision.topic} title={decision.title}"
            )
            print(f"  {decision.decision_text}")
        return

    if args.command == "tui":
        from .tui import run_tui

        run_tui(db_path=args.db_path)
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
