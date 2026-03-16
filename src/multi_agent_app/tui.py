from __future__ import annotations

import argparse
from typing import List, Tuple

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Select, Static

from .cli import (
    get_session_status,
    list_history_for_session,
    list_tasks_for_session,
    route_task_by_id,
)
from .storage import Storage

AGENT_OPTIONS: List[Tuple[str, str]] = [
    ("writer", "writer"),
    ("reviewer", "reviewer"),
    ("planner", "planner"),
]


class MultiAgentTUI(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #root { height: 1fr; }
    #left, #right { width: 1fr; padding: 1; }
    #status { padding: 1; }
    """

    def __init__(self, db_path: str = "multi_agent.db") -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root"):
            with Vertical(id="left"):
                yield Static("Sessions")
                yield Select([], prompt="Select session", id="session-select", allow_blank=True)
                yield Static("", id="sessions-view")
                yield Static("Tasks")
                yield Select([], prompt="Select task", id="task-select", allow_blank=True)
                yield Static("", id="tasks-view")
            with Vertical(id="right"):
                yield Static("Route Task")
                yield Select(AGENT_OPTIONS, value="writer", id="agent-select", allow_blank=False)
                with Horizontal():
                    yield Button("Route Task", id="route-task", variant="primary")
                    yield Button("Refresh", id="refresh")
                yield Static("", id="status")
                yield Static("Session History")
                yield Static("", id="history-view")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_sessions()

    def _status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _refresh_sessions(self) -> None:
        storage = Storage(db_path=self.db_path)
        try:
            sessions = storage.list_sessions()
        finally:
            storage.close()

        session_select = self.query_one("#session-select", Select)
        options = [(f"{session.name} [{session.status}] ({session.id[:8]})", session.id) for session in sessions]
        session_select.set_options(options)

        sessions_text = "\n".join(f"- {label}" for label, _ in options) if options else "No sessions in database."
        self.query_one("#sessions-view", Static).update(sessions_text)

        if options:
            session_select.value = options[0][1]
            self._refresh_session_details(options[0][1])
        else:
            self.query_one("#task-select", Select).set_options([])
            self.query_one("#tasks-view", Static).update("")
            self.query_one("#history-view", Static).update("")
            self._status("No sessions found. Use CLI to create a session.")

    def _refresh_session_details(self, session_id: str) -> None:
        tasks = list_tasks_for_session(self.db_path, session_id)
        history = list_history_for_session(self.db_path, session_id)
        status = get_session_status(self.db_path, session_id)

        task_select = self.query_one("#task-select", Select)
        task_options = [(f"{task.description} [{task.status}] ({task.id[:8]})", task.id) for task in tasks]
        task_select.set_options(task_options)
        if task_options:
            task_select.value = task_options[0][1]

        tasks_text = "\n".join(
            f"- {task.id} [{task.status}] owner={task.owner_agent or '-'} | {task.description}"
            for task in tasks
        )
        self.query_one("#tasks-view", Static).update(tasks_text or "No tasks for this session.")

        history_text = "\n".join(
            f"- {item['created_at'].isoformat()} [{item['source']}/{item['kind']}] {item['message']}"
            for item in history
        )
        self.query_one("#history-view", Static).update(history_text or "No history yet.")
        self._status(f"Session {session_id}: {status}")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "session-select" and isinstance(event.value, str) and event.value:
            self._refresh_session_details(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self._refresh_sessions()
            return

        if event.button.id != "route-task":
            return

        session_id = self.query_one("#session-select", Select).value
        task_id = self.query_one("#task-select", Select).value
        agent_name = self.query_one("#agent-select", Select).value

        if not isinstance(session_id, str) or not isinstance(task_id, str) or not isinstance(agent_name, str):
            self._status("Pick a session, task and agent before routing.")
            return

        try:
            action = route_task_by_id(self.db_path, task_id, agent_name)
        except Exception as exc:  # Keep UI flow simple and resilient.
            self._status(f"Routing failed: {exc}")
            self._refresh_session_details(session_id)
            return

        self._status(f"Task routed with {action.agent_name} ({action.kind})")
        self._refresh_session_details(session_id)


def run_tui(db_path: str = "multi_agent.db") -> None:
    app = MultiAgentTUI(db_path=db_path)
    app.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MultiAgentApp Textual UI.")
    parser.add_argument("--db-path", default="multi_agent.db", help="Path to SQLite database file.")
    args = parser.parse_args()
    run_tui(db_path=args.db_path)


if __name__ == "__main__":
    main()
