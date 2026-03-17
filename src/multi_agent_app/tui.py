from __future__ import annotations

import argparse
from typing import List

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static

from .cli import (
    ask_decision_panel,
)
from .storage import Storage

class MultiAgentTUI(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #root { height: 1fr; }
    #left, #middle, #right { width: 1fr; padding: 1; }
    #summary { padding: 1; border: tall $accent; }
    #active-decisions, #open-candidates, #open-suggestions, #recent-activity, #decision-detail {
      border: round $panel;
      padding: 1;
      height: 1fr;
    }
    #panel-actions { height: auto; }
    #panel-output { height: 16; border: round $panel; }
    #status { padding: 1; }
    """

    def __init__(self, db_path: str = "multi_agent.db") -> None:
        super().__init__()
        self.db_path = db_path
        self._active_decision_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root"):
            with Vertical(id="left"):
                yield Static("Summary", classes="section-title")
                yield Static("", id="summary")
                with Horizontal(id="panel-actions"):
                    yield Button("Refresh", id="refresh", variant="primary")
                yield Static("Active decisions", classes="section-title")
                yield Static("", id="active-decisions")
                yield Select([], prompt="Select active decision", id="decision-select", allow_blank=True)
            with Vertical(id="middle"):
                yield Static("Decision detail", classes="section-title")
                yield Static("", id="decision-detail")
                yield Static("Open decision candidates", classes="section-title")
                yield Static("", id="open-candidates")
            with Vertical(id="right"):
                yield Static("Open decision suggestions", classes="section-title")
                yield Static("", id="open-suggestions")
                yield Static("Recent activity", classes="section-title")
                yield Static("", id="recent-activity")
                yield Static("Ask panel", classes="section-title")
                yield Input(placeholder="Topic", id="panel-topic")
                yield Input(placeholder="Question", id="panel-question")
                with Horizontal(id="panel-actions"):
                    yield Button("Ask panel", id="ask-panel", variant="success")
                yield Static("", id="status")
                yield RichLog(id="panel-output", wrap=True, highlight=False, markup=False, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_dashboard()

    def _status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _refresh_dashboard(self) -> None:
        storage = Storage(db_path=self.db_path)
        try:
            active_decisions = storage.list_active_decisions()
            open_candidates = storage.list_open_decision_candidates()
            open_suggestions = storage.list_open_decision_suggestions()
            recent_events = storage.list_recent_session_events(limit=10)
        finally:
            storage.close()

        summary_text = (
            f"Active decisions: {len(active_decisions)}\n"
            f"Open candidates: {len(open_candidates)}\n"
            f"Open suggestions: {len(open_suggestions)}\n"
            f"Recent session events: {len(recent_events)}"
        )
        self.query_one("#summary", Static).update(summary_text)

        self._active_decision_ids = [decision.id for decision in active_decisions]
        decision_lines = []
        for decision in active_decisions:
            decision_lines.append(
                f"- {decision.id[:8]} | {decision.title} | {decision.topic} | {decision.status} | {decision.owner or '-'}"
            )
        self.query_one("#active-decisions", Static).update(
            "\n".join(decision_lines) if decision_lines else "No active decisions."
        )

        decision_select = self.query_one("#decision-select", Select)
        decision_options = [
            (
                f"{decision.id[:8]} | {decision.title} | {decision.topic} | {decision.status} | {decision.owner or '-'}",
                decision.id,
            )
            for decision in active_decisions
        ]
        decision_select.set_options(decision_options)
        if decision_options:
            decision_select.value = decision_options[0][1]
            self._render_decision_detail(decision_options[0][1])
        else:
            self.query_one("#decision-detail", Static).update("Select a decision to inspect details.")

        candidate_lines = []
        for candidate in open_candidates:
            candidate_lines.append(
                f"- {candidate.title} | {candidate.topic} | {candidate.status} | session={candidate.session_id[:8]}"
            )
        self.query_one("#open-candidates", Static).update(
            "\n".join(candidate_lines) if candidate_lines else "No open decision candidates."
        )

        suggestion_lines = []
        for suggestion in open_suggestions:
            suggestion_lines.append(
                f"- {suggestion.suggestion_type} | {suggestion.source_decision_id[:8]} -> "
                f"{suggestion.target_decision_id[:8]} | {suggestion.status}"
            )
        self.query_one("#open-suggestions", Static).update(
            "\n".join(suggestion_lines) if suggestion_lines else "No open decision suggestions."
        )

        event_lines = []
        for event in recent_events:
            event_lines.append(
                f"- {event.created_at.isoformat()} | {event.event_type} | {event.message}"
            )
        self.query_one("#recent-activity", Static).update(
            "\n".join(event_lines) if event_lines else "No recent activity."
        )
        self._status("Dashboard refreshed.")

    def _render_decision_detail(self, decision_id: str) -> None:
        storage = Storage(db_path=self.db_path)
        try:
            decision = storage.get_decision(decision_id)
            outgoing_links = storage.list_outgoing_links(decision_id)
            incoming_links = storage.list_incoming_links(decision_id)
        finally:
            storage.close()

        if decision is None:
            self.query_one("#decision-detail", Static).update(f"Decision '{decision_id}' not found.")
            return

        outgoing_text = ", ".join(
            f"{link.relation_type}:{link.to_decision_id[:8]}" for link in outgoing_links
        ) or "-"
        incoming_text = ", ".join(
            f"{link.relation_type}:{link.from_decision_id[:8]}" for link in incoming_links
        ) or "-"
        detail = (
            f"id: {decision.id}\n"
            f"title: {decision.title}\n"
            f"topic: {decision.topic}\n"
            f"status: {decision.status}\n"
            f"owner: {decision.owner or '-'}\n"
            f"text: {decision.decision_text}\n"
            f"rationale: {decision.rationale or '-'}\n"
            f"outgoing links: {outgoing_text}\n"
            f"incoming links: {incoming_text}"
        )
        self.query_one("#decision-detail", Static).update(detail)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "decision-select" and isinstance(event.value, str) and event.value:
            self._render_decision_detail(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self._refresh_dashboard()
            return

        if event.button.id != "ask-panel":
            return

        topic = self.query_one("#panel-topic", Input).value.strip()
        question = self.query_one("#panel-question", Input).value.strip()
        if not topic or not question:
            self._status("Both topic and question are required.")
            return

        output = self.query_one("#panel-output", RichLog)
        output.clear()
        try:
            panel_question, context, assessment, responses, combined, likely_new_decision, next_step = ask_decision_panel(
                db_path=self.db_path,
                question=question,
                topic=topic,
            )
        except Exception as exc:  # Keep UI flow simple and resilient.
            self._status(f"Panel failed: {exc}")
            return

        by_agent = {response.agent_name: response.response_text for response in responses}
        output.write(f"Question: {panel_question.question}")
        output.write(f"Topic: {panel_question.topic}")
        output.write(
            "Relevant active decisions: "
            + (
                ", ".join(f"{d.id[:8]}:{d.title}" for d in context["active_decisions"])
                if context["active_decisions"]
                else "none"
            )
        )
        output.write(
            "Historical decisions: "
            + (
                ", ".join(f"{d.id[:8]}:{d.title}" for d in context["historical_decisions"])
                if context["historical_decisions"]
                else "none"
            )
        )
        output.write(
            "Open decision candidates: "
            + (
                ", ".join(f"{c.id[:8]}:{c.title}" for c in context["open_candidates"])
                if context["open_candidates"]
                else "none"
            )
        )
        output.write(
            "Open decision suggestions: "
            + (
                ", ".join(f"{s.id[:8]}:{s.suggestion_type}" for s in context["open_suggestions"])
                if context["open_suggestions"]
                else "none"
            )
        )
        output.write(f"Decision alignment assessment: {assessment.alignment} ({assessment.reason})")
        output.write(
            "Challenge points: "
            + (" | ".join(assessment.challenge_points) if assessment.challenge_points else "none")
        )
        output.write(f"Strateg: {by_agent['strateg']}")
        output.write(f"Analyst: {by_agent['analyst']}")
        output.write(f"Operator: {by_agent['operator']}")
        output.write(f"Governance: {by_agent['governance']}")
        output.write(f"Combined recommendation: {combined}")
        output.write(f"Likely requires new decision?: {likely_new_decision}")
        output.write(f"Suggested next step: {next_step}")
        self._status("Panel response generated.")
        self._refresh_dashboard()


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
