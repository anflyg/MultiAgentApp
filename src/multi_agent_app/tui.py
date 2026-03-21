from __future__ import annotations

import argparse
from typing import List

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static

from .cli import (
    ask_decision_panel,
)
from .panel import alignment_label, build_panel_outcome, decision_mode_label, likelihood_label
from .storage import Storage

_ROLE_SOURCE_LABELS = {
    "llm": "LLM",
    "heuristic": "heuristic fallback",
}

class MultiAgentTUI(App[None]):
    CSS = """
    Screen { layout: vertical; }
    #root { height: 1fr; }
    #left, #middle, #right { width: 1fr; padding: 1; }
    #summary {
      padding: 1;
      border: tall $accent;
      height: auto;
      min-height: 4;
    }
    #question-analysis, #question-recommendation, #question-status,
    #active-decisions, #open-candidates, #open-suggestions, #recent-activity, #decision-detail {
      border: round $panel;
      padding: 1;
      height: 1fr;
      min-height: 4;
      overflow-y: auto;
    }
    #recent-questions {
      border: round $panel;
      padding: 1;
      height: 6;
      min-height: 4;
      overflow-y: auto;
    }
    #question-select {
      height: auto;
      min-height: 3;
      margin-top: 0;
      margin-bottom: 1;
      border: round $accent;
    }
    #active-decisions {
      min-height: 6;
    }
    #question-analysis { height: 2fr; min-height: 7; }
    #question-recommendation, #question-status { min-height: 5; }
    #panel-actions { height: auto; }
    #panel-output { height: 16; border: round $panel; }
    #status { padding: 1; }
    """

    def __init__(self, db_path: str = "multi_agent.db") -> None:
        super().__init__()
        self.db_path = db_path
        self._active_decision_ids: list[str] = []
        self._recent_question_ids: list[str] = []
        self._selected_question_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root"):
            with Vertical(id="left"):
                yield Static("Summary", classes="section-title")
                yield Static("", id="summary")
                with Horizontal(id="panel-actions"):
                    yield Button("Refresh", id="refresh", variant="primary")
                yield Static("Latest questions", classes="section-title")
                yield Select([], prompt="Select question", id="question-select", allow_blank=True)
                yield Static("", id="recent-questions")
                yield Static("Active decisions", classes="section-title")
                yield Static("", id="active-decisions")
                yield Select([], prompt="Select active decision", id="decision-select", allow_blank=True)
            with Vertical(id="middle"):
                yield Static("Selected question brief", classes="section-title")
                yield Static("", id="question-analysis")
                yield Static("Panel recommendation", classes="section-title")
                yield Static("", id="question-recommendation")
                yield Static("Decision guidance", classes="section-title")
                yield Static("", id="question-status")
                yield Static("Decision detail", classes="section-title")
                yield Static("", id="decision-detail")
            with Vertical(id="right"):
                yield Static("Pending decision candidates", classes="section-title")
                yield Static("", id="open-candidates")
                yield Static("Pending decision suggestions", classes="section-title")
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

    def _resolve_select_value(self, value: object) -> str | None:
        if value is None or value == Select.BLANK:
            return None
        if isinstance(value, str):
            return value if value else None
        nested_value = getattr(value, "value", None)
        if isinstance(nested_value, str):
            return nested_value if nested_value else None
        return None

    def _pick_question_id_after_refresh(self, available_question_ids: list[str]) -> str | None:
        if not available_question_ids:
            return None
        if self._selected_question_id and self._selected_question_id in available_question_ids:
            return self._selected_question_id
        return available_question_ids[0]

    def _schedule_question_render(self, question_id: str) -> None:
        self.call_later(self._render_question_analysis, question_id)

    def _refresh_dashboard(self) -> None:
        storage = Storage(db_path=self.db_path)
        try:
            active_decisions = storage.list_active_decisions()
            open_candidates = storage.list_open_decision_candidates()
            open_suggestions = storage.list_open_decision_suggestions()
            recent_events = storage.list_recent_session_events(limit=10)
            recent_questions = storage.list_panel_questions(limit=10)
        finally:
            storage.close()

        summary_text = (
            f"Recent questions: {len(recent_questions)}\n"
            f"Active decisions: {len(active_decisions)}\n"
            f"Pending candidates: {len(open_candidates)}\n"
            f"Pending suggestions: {len(open_suggestions)}\n"
            f"Recent session events: {len(recent_events)}"
        )
        self.query_one("#summary", Static).update(summary_text)

        self._recent_question_ids = [question.id for question in recent_questions]
        question_lines = []
        for question in recent_questions[:5]:
            summary = " ".join(question.question_text.split())
            if len(summary) > 52:
                summary = summary[:49].rstrip() + "..."
            question_lines.append(
                f"- {question.id[:8]} | {question.topic} | {summary}"
            )
        self.query_one("#recent-questions", Static).update(
            "\n".join(question_lines)
            if question_lines
            else "No previous panel questions yet. Use Ask panel on the right to create your first one."
        )

        question_select = self.query_one("#question-select", Select)
        current_selected_question = self._resolve_select_value(question_select.value)
        if current_selected_question:
            self._selected_question_id = current_selected_question
        question_options = [
            (
                f"{question.id[:8]} | {question.created_at.isoformat()} | {question.topic} | {question.status}",
                question.id,
            )
            for question in recent_questions
        ]
        question_select.set_options(question_options)
        selected_question_id = self._pick_question_id_after_refresh(self._recent_question_ids)
        if selected_question_id is not None:
            self._selected_question_id = selected_question_id
            if self._resolve_select_value(question_select.value) != selected_question_id:
                question_select.value = selected_question_id
            self._schedule_question_render(selected_question_id)
        else:
            self.query_one("#question-analysis", Static).update("Select a question to inspect analysis.")
            self.query_one("#question-recommendation", Static).update("No recommendation available yet.")
            self.query_one("#question-status", Static).update("No decision guidance available yet.")

        self._active_decision_ids = [decision.id for decision in active_decisions]
        decision_lines = []
        for decision in active_decisions:
            decision_lines.append(
                f"- {decision.id[:8]} | {decision.title} | {decision.topic} | {decision.status} | {decision.owner or '-'}"
            )
        self.query_one("#active-decisions", Static).update(
            "\n".join(decision_lines)
            if decision_lines
            else "No active decisions yet. Run alpha-demo-setup or create one via CLI."
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
            "\n".join(candidate_lines)
            if candidate_lines
            else "No pending decision candidates right now."
        )

        suggestion_lines = []
        for suggestion in open_suggestions:
            suggestion_lines.append(
                f"- {suggestion.suggestion_type} | {suggestion.source_decision_id[:8]} -> "
                f"{suggestion.target_decision_id[:8]} | {suggestion.status}"
            )
        self.query_one("#open-suggestions", Static).update(
            "\n".join(suggestion_lines)
            if suggestion_lines
            else "No pending decision suggestions right now."
        )

        event_lines = []
        for event in recent_events:
            event_lines.append(
                f"- {event.created_at.isoformat()} | {event.event_type} | {event.message}"
            )
        self.query_one("#recent-activity", Static).update(
            "\n".join(event_lines) if event_lines else "No recent activity."
        )
        if recent_questions:
            self._status(
                "Dashboard refreshed. Happy path: select a question on the left, review recommendation in the center, then ask a new panel question on the right."
            )
        else:
            self._status(
                "Dashboard refreshed. Happy path: use Ask panel on the right to create your first question, then select it on the left."
            )

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

    def _build_question_detail_texts(self, case: dict | None) -> tuple[str, str, str]:
        if case is None:
            return (
                "Selected question was not found.",
                "No recommendation available yet.",
                "No decision guidance available yet.",
            )

        question = case["question"]
        analysis = case.get("analysis")
        sections = case.get("sections", {}) or {}

        interpretation = sections.get("question_interpretation")
        if not interpretation and analysis is not None:
            interpretation = analysis.assessment_reason

        context_parts = []
        signal_parts = []
        relevant_context = sections.get("relevant_context", {})
        if isinstance(relevant_context, dict):
            active_ids = relevant_context.get("active_decision_ids", [])
            historical_ids = relevant_context.get("historical_decision_ids", [])
            open_candidate_ids = relevant_context.get("open_candidate_ids", [])
            open_suggestion_ids = relevant_context.get("open_suggestion_ids", [])
            if active_ids:
                context_parts.append("active=" + ", ".join(active_ids))
            if historical_ids:
                context_parts.append("historical=" + ", ".join(historical_ids))
            signal_parts.append(f"active={len(active_ids)}")
            signal_parts.append(f"historical={len(historical_ids)}")
            signal_parts.append(f"open_candidates={len(open_candidate_ids)}")
            signal_parts.append(f"open_suggestions={len(open_suggestion_ids)}")
        context_line = " | ".join(context_parts) if context_parts else "none"

        role_lines = []
        role_analysis = sections.get("per_role_analysis", {})
        status_assessment = sections.get("decision_status_assessment", {})
        llm_status = (
            status_assessment.get("llm_status", {})
            if isinstance(status_assessment, dict)
            else {}
        )
        role_sources = (
            llm_status.get("role_sources", {})
            if isinstance(llm_status, dict)
            else {}
        )
        fallback_reasons = (
            llm_status.get("fallback_reasons", {})
            if isinstance(llm_status, dict)
            else {}
        )
        if isinstance(role_analysis, dict):
            for role_name in ("strateg", "analyst", "operator", "governance"):
                if role_name in role_analysis:
                    source = _ROLE_SOURCE_LABELS.get(
                        role_sources.get(role_name, "heuristic"),
                        role_sources.get(role_name, "heuristic"),
                    )
                    role_lines.append(f"- {role_name} [{source}]: {role_analysis[role_name]}")
        tensions = sections.get("tensions", []) or []
        tensions_text = " | ".join(tensions) if tensions else "none"
        reasoning_items = case.get("reasoning_items", []) or []
        kind_priority = {
            "objection": 0,
            "risk": 1,
            "open_question": 2,
            "assumption": 3,
            "rationale": 4,
        }
        kind_labels = {
            "objection": "Critical objection",
            "risk": "Risk signal",
            "open_question": "Open question",
            "assumption": "Assumption to verify",
            "rationale": "Supporting rationale",
        }
        source_labels = {
            "panel": "panel analysis",
            "system": "system memory",
            "operator": "operator input",
            "agent": "agent input",
            "manual": "manual note",
        }
        visibility_labels = {
            "transient": "temporary context",
            "private_context": "private context",
            "formal_decision": "formal decision context",
        }
        reasoning_lines = []
        for item in sorted(
            reasoning_items,
            key=lambda x: (kind_priority.get(x.kind, 99), x.created_at),
        )[:4]:
            content = " ".join(item.content.split())
            if len(content) > 88:
                content = content[:85].rstrip() + "..."
            kind_label = kind_labels.get(item.kind, item.kind.replace("_", " "))
            source_label = source_labels.get(item.source_type, item.source_type)
            visibility_label = visibility_labels.get(item.memory_level, item.memory_level)
            reasoning_lines.append(
                f"- {kind_label}: {content} ({source_label}; {visibility_label})"
            )
        if not signal_parts:
            signal_parts = ["active=0", "historical=0", "open_candidates=0", "open_suggestions=0"]
        signal_parts.append(f"reasoning_items={len(reasoning_items)}")
        analysis_text = (
            f"Question: {question.question_text}\n"
            f"Topic: {question.topic}\n"
            f"Status: {question.status}\n"
            f"Interpretation: {interpretation or '-'}\n"
            f"Relevant context: {context_line}\n"
            f"Context and memory signals: {' | '.join(signal_parts)}\n"
            f"Tensions: {tensions_text}\n"
            f"Advisor perspectives:\n"
            + ("\n".join(role_lines) if role_lines else "- none")
            + "\nKey reasoning notes:\n"
            + ("\n".join(reasoning_lines) if reasoning_lines else "- none")
        )

        combined = sections.get("combined_recommendation")
        if not combined and analysis is not None:
            combined = analysis.combined_recommendation
        recommendation_text = combined or "No recommendation available yet."

        if isinstance(status_assessment, dict) and status_assessment:
            mode_value = status_assessment.get("decision_mode", "-")
            provider_name = llm_status.get("provider", "heuristic") if isinstance(llm_status, dict) else "heuristic"
            provider_model = llm_status.get("model") if isinstance(llm_status, dict) else None
            provider_enabled = bool(llm_status.get("provider_enabled")) if isinstance(llm_status, dict) else False
            provider_available = bool(llm_status.get("provider_available")) if isinstance(llm_status, dict) else False
            fallback_text = (
                ", ".join(f"{role}={reason}" for role, reason in sorted(fallback_reasons.items()))
                if fallback_reasons
                else "-"
            )
            status_text = (
                f"assessment: {alignment_label(status_assessment.get('alignment', '-'))}\n"
                f"handling mode: {decision_mode_label(mode_value) if mode_value != '-' else '-'}\n"
                f"reason: {status_assessment.get('reason', '-')}\n"
                f"role generation: provider={provider_name}"
                f"{f' ({provider_model})' if provider_model else ''} | enabled={'yes' if provider_enabled else 'no'} | "
                f"available={'yes' if provider_available else 'no'}\n"
                f"fallback notes: {fallback_text}\n"
                f"new decision likelihood: {likelihood_label(status_assessment.get('likely_requires_new_decision', '-'))}\n"
                f"formal_next_step: {status_assessment.get('formal_next_step', '-')}\n"
                f"suggested_next_step: {status_assessment.get('suggested_next_step', '-')}"
            )
        elif analysis is not None:
            status_text = (
                f"assessment: {alignment_label(analysis.assessment_alignment)}\n"
                f"reason: {analysis.assessment_reason}\n"
                f"new decision likelihood: {likelihood_label(analysis.likely_requires_new_decision)}"
            )
        else:
            status_text = "No decision guidance available yet."

        return analysis_text, recommendation_text, status_text

    def _render_question_analysis(self, question_id: str) -> None:
        storage = Storage(db_path=self.db_path)
        try:
            case = storage.get_panel_question_case(question_id)
        finally:
            storage.close()

        analysis_text, recommendation_text, status_text = self._build_question_detail_texts(case)
        self.query_one("#question-analysis", Static).update(analysis_text)
        self.query_one("#question-recommendation", Static).update(recommendation_text)
        self.query_one("#question-status", Static).update(status_text)

    def on_select_changed(self, event: Select.Changed) -> None:
        selected_value = self._resolve_select_value(event.value)
        if event.select.id == "question-select" and selected_value:
            self._selected_question_id = selected_value
            self._schedule_question_render(selected_value)
            return
        if event.select.id == "decision-select" and selected_value:
            self._render_decision_detail(selected_value)

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
        storage = Storage(db_path=self.db_path)
        try:
            stored_analysis = storage.get_panel_question_analysis(panel_question.id)
        finally:
            storage.close()
        status_payload = stored_analysis.decision_status_assessment if stored_analysis else {}
        llm_status = status_payload.get("llm_status", {}) if isinstance(status_payload, dict) else {}
        role_sources = llm_status.get("role_sources", {}) if isinstance(llm_status, dict) else {}
        fallback_reasons = llm_status.get("fallback_reasons", {}) if isinstance(llm_status, dict) else {}
        provider_name = llm_status.get("provider", "heuristic") if isinstance(llm_status, dict) else "heuristic"
        provider_model = llm_status.get("model") if isinstance(llm_status, dict) else None
        provider_enabled = bool(llm_status.get("provider_enabled")) if isinstance(llm_status, dict) else False
        provider_available = bool(llm_status.get("provider_available")) if isinstance(llm_status, dict) else False
        output.write(f"Question: {panel_question.question_text}")
        output.write(f"Topic: {panel_question.topic}")
        output.write(
            "Active decisions in scope: "
            + (
                ", ".join(f"{d.id[:8]}:{d.title}" for d in context["active_decisions"])
                if context["active_decisions"]
                else "none"
            )
        )
        output.write(
            "Previous related decisions: "
            + (
                ", ".join(f"{d.id[:8]}:{d.title}" for d in context["historical_decisions"])
                if context["historical_decisions"]
                else "none"
            )
        )
        output.write(
            "Pending decision candidates: "
            + (
                ", ".join(f"{c.id[:8]}:{c.title}" for c in context["open_candidates"])
                if context["open_candidates"]
                else "none"
            )
        )
        output.write(
            "Pending decision suggestions: "
            + (
                ", ".join(f"{s.id[:8]}:{s.suggestion_type}" for s in context["open_suggestions"])
                if context["open_suggestions"]
                else "none"
            )
        )
        panel_outcome = build_panel_outcome(context, assessment)
        output.write(f"Assessment: {alignment_label(assessment.alignment)} ({assessment.reason})")
        output.write(
            "Decision summary: "
            f"Assessment: {alignment_label(assessment.alignment)} | "
            f"Mode: {decision_mode_label(panel_outcome.decision_mode)} | "
            f"New decision likelihood: {likelihood_label(panel_outcome.likely_requires_new_decision)}"
        )
        output.write(
            "Role generation mode: "
            f"provider={provider_name}"
            f"{f' ({provider_model})' if provider_model else ''} | enabled={'yes' if provider_enabled else 'no'} | "
            f"available={'yes' if provider_available else 'no'}"
        )
        if fallback_reasons:
            output.write(
                "Fallback notes: "
                + ", ".join(f"{role}={reason}" for role, reason in sorted(fallback_reasons.items()))
            )
        output.write(
            "Decision context at a glance: "
            f"active={len(context['active_decisions'])} | historical={len(context['historical_decisions'])} | "
            f"open_candidates={len(context['open_candidates'])} | open_suggestions={len(context['open_suggestions'])}"
        )
        output.write(
            "Key concerns: "
            + (" | ".join(assessment.challenge_points) if assessment.challenge_points else "none")
        )
        output.write(
            "Strateg "
            f"[{_ROLE_SOURCE_LABELS.get(role_sources.get('strateg', 'heuristic'), role_sources.get('strateg', 'heuristic'))}]: "
            f"{by_agent['strateg']}"
        )
        output.write(
            "Analyst "
            f"[{_ROLE_SOURCE_LABELS.get(role_sources.get('analyst', 'heuristic'), role_sources.get('analyst', 'heuristic'))}]: "
            f"{by_agent['analyst']}"
        )
        output.write(
            "Operator "
            f"[{_ROLE_SOURCE_LABELS.get(role_sources.get('operator', 'heuristic'), role_sources.get('operator', 'heuristic'))}]: "
            f"{by_agent['operator']}"
        )
        output.write(
            "Governance "
            f"[{_ROLE_SOURCE_LABELS.get(role_sources.get('governance', 'heuristic'), role_sources.get('governance', 'heuristic'))}]: "
            f"{by_agent['governance']}"
        )
        output.write(f"Combined recommendation: {combined}")
        output.write(f"Formal next step: {panel_outcome.formal_next_step}")
        output.write(f"New decision likely?: {likelihood_label(likely_new_decision)}")
        output.write(f"Recommended next step: {next_step}")
        self._status("Panel response generated.")
        self._selected_question_id = panel_question.id
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
