from __future__ import annotations

import re
from typing import TypedDict

from . import models
from .storage import Storage


class PanelContext(TypedDict):
    active_decisions: list[models.Decision]
    historical_decisions: list[models.Decision]
    open_candidates: list[models.DecisionCandidate]
    open_suggestions: list[models.DecisionSuggestion]
    decision_links: list[models.DecisionLink]


class PanelSections(TypedDict):
    question_interpretation: str
    relevant_context: dict[str, object]
    per_role_analysis: dict[str, str]
    tensions: list[str]
    combined_recommendation: str
    decision_status_assessment: dict[str, object]


_DEVIATION_SIGNALS = [
    "ändå",
    "trots",
    "i stället",
    "ändra",
    "byta",
    "ompröva",
    "gå vidare med",
    "öppna danmark ändå",
    "instead",
    "despite",
    "override",
    "bypass",
]

_STRONG_CONFLICT_SIGNALS = [
    "ändå",
    "trots",
    "i stället",
    "override",
    "bypass",
    "despite",
    "öppna danmark ändå",
]

_EXECUTION_SIGNALS = [
    "hur",
    "implementera",
    "vem",
    "när",
    "nästa steg",
    "förtydliga",
    "how",
    "implement",
    "who",
    "when",
    "next step",
]

_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "into",
    "som",
    "och",
    "det",
    "den",
    "att",
    "från",
    "med",
    "ska",
    "kan",
    "vad",
    "hur",
    "när",
    "vem",
    "topic",
    "decision",
}


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _contains_any(text: str, terms: list[str]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if term in text:
            hits.append(term)
    return hits


def _keywords(text: str) -> set[str]:
    tokens = re.findall(r"[a-zåäö0-9]{3,}", _normalize(text))
    return {token for token in tokens if token not in _STOPWORDS}


def assess_question_against_active_decisions(
    question: str, active_decisions: list[models.Decision]
) -> models.DecisionAlignmentAssessment:
    normalized_question = _normalize(question)
    if not active_decisions:
        return models.DecisionAlignmentAssessment(
            alignment="clarification_needed",
            reason="No active governing decisions were found for this topic.",
            challenge_points=["No active decision baseline exists yet."],
        )

    decision_ids = [decision.id for decision in active_decisions]
    question_keywords = _keywords(normalized_question)
    decision_keywords: set[str] = set()
    for decision in active_decisions:
        decision_keywords |= _keywords(f"{decision.title} {decision.decision_text}")
    overlap = sorted(question_keywords & decision_keywords)

    deviation_hits = _contains_any(normalized_question, _DEVIATION_SIGNALS)
    strong_conflict_hits = _contains_any(normalized_question, _STRONG_CONFLICT_SIGNALS)
    execution_hits = _contains_any(normalized_question, _EXECUTION_SIGNALS)

    if strong_conflict_hits:
        challenge_points = [
            f"Question includes strong deviation signals: {', '.join(sorted(set(strong_conflict_hits)))}.",
            "Question should be treated as likely inconsistent with current active direction.",
        ]
        challenge_points.extend(
            f"Review active decision {decision.id} ({decision.title}) before proceeding."
            for decision in active_decisions[:3]
        )
        return models.DecisionAlignmentAssessment(
            alignment="likely_new_decision_required",
            reason="Question likely proposes an exception or reversal against active decisions.",
            active_decision_ids=decision_ids,
            challenge_points=challenge_points,
        )

    if deviation_hits:
        challenge_points = [
            f"Question includes deviation signals: {', '.join(sorted(set(deviation_hits)))}.",
            "Validate whether this is a controlled exception or a decision change.",
        ]
        challenge_points.extend(
            f"Check impact on active decision {decision.id} ({decision.title})."
            for decision in active_decisions[:3]
        )
        return models.DecisionAlignmentAssessment(
            alignment="potential_deviation",
            reason="Question may diverge from current direction and should be challenged explicitly.",
            active_decision_ids=decision_ids,
            challenge_points=challenge_points,
        )

    if execution_hits:
        return models.DecisionAlignmentAssessment(
            alignment="clarification_needed",
            reason="Question appears execution-oriented and needs operational clarification within active decisions.",
            active_decision_ids=decision_ids,
            challenge_points=["Clarify execution details, ownership, and sequencing against active decisions."],
        )

    if overlap:
        return models.DecisionAlignmentAssessment(
            alignment="aligned",
            reason="Question appears aligned with active decision content.",
            active_decision_ids=decision_ids,
            challenge_points=[],
        )

    return models.DecisionAlignmentAssessment(
        alignment="clarification_needed",
        reason="Question does not map clearly to active decision wording; clarification is needed.",
        active_decision_ids=decision_ids,
        challenge_points=["Clarify which active decision this question is intended to follow."],
    )


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


def strateg_response(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if assessment.alignment == "likely_new_decision_required":
        return (
            "Question appears to challenge current strategic direction and should not be treated as normal execution. "
            "Escalate as a new decision request."
        )
    if assessment.alignment == "potential_deviation":
        return (
            "Question may signal a strategic deviation. Confirm if this is an intentional direction change before "
            "continuing."
        )
    if assessment.alignment == "clarification_needed":
        return "Question reads as execution/clarification work; strategic direction remains governed by active decisions."
    return "Question appears aligned with current strategic direction and can proceed under active decisions."


def analyst_response(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
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


def operator_response(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if not context["active_decisions"]:
        return "First create a concrete decision for this topic, then assign owner and implementation steps."
    if assessment.alignment in {"potential_deviation", "likely_new_decision_required"}:
        return (
            "Pause rollout changes and open explicit decision handling. Keep current implementation constrained to "
            "existing active decisions until governance confirms."
        )
    return (
        "Execute against active decisions, confirm ownership, and convert open suggestions/candidates into explicit "
        "accept, dismiss, or new decision actions."
    )


def governance_response(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if not context["active_decisions"]:
        return "No active governing decisions were found for this topic."
    governed = ", ".join(
        f"{decision.id} ({decision.title})" for decision in context["active_decisions"][:5]
    )
    if assessment.alignment == "aligned":
        mode = "execution within current decision"
    elif assessment.alignment == "clarification_needed":
        mode = "clarification of current decision"
    else:
        mode = "potential new decision"
    return f"Active governing decisions: {governed}. Treat this question as: {mode}."


def likely_requires_new_decision(assessment: models.DecisionAlignmentAssessment) -> str:
    if assessment.alignment == "aligned":
        return "no"
    if assessment.alignment == "likely_new_decision_required":
        return "yes"
    return "probably"


def combined_recommendation(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if not context["active_decisions"]:
        return "Create and confirm a new decision for this topic before execution."
    if assessment.alignment == "likely_new_decision_required":
        return (
            "Do not proceed as routine execution. Raise an explicit new decision, document the proposed deviation, "
            "and resolve governance before action."
        )
    if assessment.alignment == "potential_deviation":
        return (
            "Treat as possible deviation: capture exception rationale, run leadership review, and decide whether to "
            "amend or supersede active decisions."
        )
    if context["open_suggestions"] or context["open_candidates"]:
        return "Review open suggestions/candidates first, then either link or record a new decision."
    return "Proceed with execution under current active decisions and monitor for new conflicts."


def suggested_next_step(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if not context["active_decisions"]:
        return "Create a decision candidate and run confirmation."
    if assessment.alignment == "likely_new_decision_required":
        return "Create a new decision candidate describing the intended deviation and submit for confirmation."
    if assessment.alignment == "potential_deviation":
        return "Create an explicit clarification/exception candidate before changing execution direction."
    if context["open_suggestions"]:
        return "List and resolve open decision suggestions for this topic."
    if context["open_candidates"]:
        return "Confirm or dismiss open decision candidates for this topic."
    return "Assign implementation owner for the active decision set."


def question_interpretation(
    question: str, context: PanelContext, assessment: models.DecisionAlignmentAssessment
) -> str:
    if not context["active_decisions"]:
        return "Question is interpreted as requiring a new baseline decision because no active governing decision exists."
    if assessment.alignment == "aligned":
        return "Question is interpreted as execution under existing active decisions."
    if assessment.alignment == "clarification_needed":
        return "Question is interpreted as clarification/execution detail within current direction."
    if assessment.alignment == "potential_deviation":
        return "Question is interpreted as a possible deviation that needs explicit challenge."
    return "Question is interpreted as likely requiring an explicit exception or new decision."


def relevant_context_summary(context: PanelContext) -> dict[str, object]:
    return {
        "active_decision_ids": [decision.id for decision in context["active_decisions"]],
        "historical_decision_ids": [decision.id for decision in context["historical_decisions"]],
        "open_candidate_ids": [candidate.id for candidate in context["open_candidates"]],
        "open_suggestion_ids": [suggestion.id for suggestion in context["open_suggestions"]],
        "decision_link_ids": [link.id for link in context["decision_links"]],
    }


def build_panel_sections(
    question: str,
    context: PanelContext,
    assessment: models.DecisionAlignmentAssessment,
    per_role_analysis: dict[str, str],
    combined: str,
    likely_new_decision: str,
) -> PanelSections:
    return {
        "question_interpretation": question_interpretation(question, context, assessment),
        "relevant_context": relevant_context_summary(context),
        "per_role_analysis": per_role_analysis,
        "tensions": assessment.challenge_points,
        "combined_recommendation": combined,
        "decision_status_assessment": {
            "alignment": assessment.alignment,
            "reason": assessment.reason,
            "likely_requires_new_decision": likely_new_decision,
        },
    }
