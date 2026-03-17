from __future__ import annotations

from typing import TypedDict

from . import models
from .storage import Storage


class PanelContext(TypedDict):
    active_decisions: list[models.Decision]
    historical_decisions: list[models.Decision]
    open_candidates: list[models.DecisionCandidate]
    open_suggestions: list[models.DecisionSuggestion]
    decision_links: list[models.DecisionLink]


def build_context_packet(
    storage: Storage, topic: str, session_id: str | None = None
) -> PanelContext:
    if session_id:
        decisions = storage.list_decisions_for_session(session_id)
        candidates = storage.list_decision_candidates_for_session(session_id)
    else:
        decisions = []
        for session in storage.list_sessions():
            decisions.extend(storage.list_decisions_for_session(session.id))
        candidates = []
        for session in storage.list_sessions():
            candidates.extend(storage.list_decision_candidates_for_session(session.id))

    topic_decisions = [decision for decision in decisions if decision.topic == topic]
    active_decisions = [decision for decision in topic_decisions if decision.status == "active"]
    historical_decisions = [decision for decision in topic_decisions if decision.status == "superseded"]
    open_candidates = [
        candidate
        for candidate in candidates
        if candidate.topic == topic and candidate.status == "proposed"
    ]

    relevant_suggestions: list[models.DecisionSuggestion] = []
    for suggestion in storage.list_open_suggestions():
        source = storage.get_decision(suggestion.source_decision_id)
        target = storage.get_decision(suggestion.target_decision_id)
        if source is None or target is None:
            continue
        if source.topic != topic and target.topic != topic:
            continue
        if session_id and source.session_id != session_id and target.session_id != session_id:
            continue
        relevant_suggestions.append(suggestion)

    unique_links: dict[str, models.DecisionLink] = {}
    for decision in active_decisions:
        for link in storage.list_links_for_decision(decision.id):
            unique_links[link.id] = link

    return {
        "active_decisions": active_decisions,
        "historical_decisions": historical_decisions,
        "open_candidates": open_candidates,
        "open_suggestions": relevant_suggestions,
        "decision_links": list(unique_links.values()),
    }


def strateg_response(question: str, context: PanelContext) -> str:
    if not context["active_decisions"]:
        return "No active decisions exist for this topic, so strategic direction is currently undefined."
    if context["open_suggestions"]:
        return (
            "Current strategy has active guidance, but open suggestions indicate potential directional updates "
            "or clarifications."
        )
    return "Current strategic direction appears stable and consistent with active decisions in this topic."


def analyst_response(question: str, context: PanelContext) -> str:
    risk_flags: list[str] = []
    if context["open_suggestions"]:
        risk_flags.append(f"{len(context['open_suggestions'])} open suggestion(s)")
    if context["open_candidates"]:
        risk_flags.append(f"{len(context['open_candidates'])} open candidate(s)")
    if context["historical_decisions"]:
        risk_flags.append(f"{len(context['historical_decisions'])} historical decision(s)")
    if not risk_flags:
        return "Low visible tension in stored records, but assumptions behind active decisions may still need verification."
    return "Potential risk indicators: " + ", ".join(risk_flags) + "."


def operator_response(question: str, context: PanelContext) -> str:
    if not context["active_decisions"]:
        return "First create a concrete decision for this topic, then assign owner and implementation steps."
    return (
        "Execute against active decisions, confirm ownership, and convert open suggestions/candidates into explicit "
        "accept, dismiss, or new decision actions."
    )


def governance_response(question: str, context: PanelContext) -> str:
    if not context["active_decisions"]:
        return "No active governing decisions were found for this topic."
    governed = ", ".join(decision.id for decision in context["active_decisions"][:5])
    return f"Active governing decisions for this topic: {governed}."


def likely_requires_new_decision(question: str, context: PanelContext) -> str:
    normalized_question = question.lower()
    divergence_words = [
        "change",
        "replace",
        "switch",
        "instead",
        "reconsider",
        "override",
        "deprecate",
        "migrate",
        "stop",
    ]
    execution_words = [
        "how",
        "when",
        "who",
        "implement",
        "rollout",
        "timeline",
        "execute",
        "operational",
    ]
    has_divergence = any(word in normalized_question for word in divergence_words)
    has_execution = any(word in normalized_question for word in execution_words)

    if has_divergence and context["active_decisions"]:
        return "yes"
    if has_execution and context["active_decisions"] and not context["open_suggestions"]:
        return "no"
    return "probably"


def combined_recommendation(question: str, context: PanelContext) -> str:
    if not context["active_decisions"]:
        return "Create and confirm a new decision for this topic before execution."
    if context["open_suggestions"] or context["open_candidates"]:
        return "Review open suggestions/candidates first, then either link or record a new decision."
    return "Proceed with execution under current active decisions and monitor for new conflicts."


def suggested_next_step(question: str, context: PanelContext) -> str:
    if not context["active_decisions"]:
        return "Create a decision candidate and run confirmation."
    if context["open_suggestions"]:
        return "List and resolve open decision suggestions for this topic."
    if context["open_candidates"]:
        return "Confirm or dismiss open decision candidates for this topic."
    return "Assign implementation owner for the active decision set."

