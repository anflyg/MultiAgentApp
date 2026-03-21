from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from typing import Dict, List

from . import models
from .agents import BaseAgent, PlannerAgent, ReviewerAgent, WriterAgent
from .llm import (
    LLMProvider,
    apply_role_llm_overrides,
    provider_enabled_from_env,
    provider_from_env,
)
from .orchestrator import OrchestrationError, Orchestrator
from .panel import (
    active_advisor_roles,
    alignment_label,
    assess_question_against_active_decisions,
    build_panel_outcome,
    build_panel_sections,
    build_context_packet,
    combined_recommendation,
    decision_mode_label,
    default_advisor_roles,
    likelihood_label,
    per_role_analysis,
    suggested_next_step,
)
from .storage import Storage

_RELATION_TYPES = {"supersedes", "clarifies", "supplements"}
_AUTO_LINKABLE_SUGGESTIONS = {
    "related_decision": "supplements",
    "possible_supersedes": "supersedes",
}
_DECISION_DRAFT_MODES = {"potential_deviation", "likely_new_decision_required"}
_REASONING_KIND_PRIORITY = {
    "objection": 0,
    "risk": 1,
    "open_question": 2,
    "assumption": 3,
    "rationale": 4,
}
_REASONING_KIND_LABEL = {
    "objection": "Critical objection",
    "risk": "Risk signal",
    "open_question": "Open question",
    "assumption": "Assumption to verify",
    "rationale": "Supporting rationale",
}
_REASONING_SOURCE_LABEL = {
    "panel": "panel analysis",
    "system": "system memory",
    "operator": "operator input",
    "agent": "agent input",
    "manual": "manual note",
}
_REASONING_VISIBILITY_LABEL = {
    "transient": "temporary context",
    "private_context": "private context",
    "formal_decision": "formal decision context",
}
_ROLE_RESPONSE_SOURCE_LABEL = {
    "llm": "LLM",
    "heuristic": "heuristic fallback",
}


def _add_suggestion_event(
    storage: Storage,
    source_decision: models.Decision,
    target_decision: models.Decision,
    event_type: str,
    message: str,
) -> None:
    storage.add_session_event(
        models.SessionEvent(
            session_id=source_decision.session_id,
            event_type=event_type,
            message=message,
        )
    )
    if source_decision.session_id != target_decision.session_id:
        storage.add_session_event(
            models.SessionEvent(
                session_id=target_decision.session_id,
                event_type=event_type,
                message=message,
            )
        )


def _default_agents() -> Dict[str, BaseAgent]:
    return {
        "writer": WriterAgent(),
        "reviewer": ReviewerAgent(),
        "planner": PlannerAgent(),
    }


def _role_response_source_label(source: str) -> str:
    return _ROLE_RESPONSE_SOURCE_LABEL.get(source, source)


def _reasoning_signature(
    item: models.ReasoningItem,
) -> tuple[str | None, str | None, str, str, str, str]:
    return (
        item.decision_id,
        item.question_id,
        item.kind,
        " ".join(item.content.strip().split()),
        item.source_type,
        item.memory_level,
    )


def _panel_reasoning_memory_level(
    *,
    kind: str,
    decision_id: str | None,
    alignment: str,
) -> str:
    if kind == "open_question" and decision_id is None:
        return "transient"
    if alignment == "aligned" and decision_id and kind in {"rationale", "assumption"}:
        return "formal_decision"
    return "private_context"


def _build_reasoning_items_from_panel(
    panel_question: models.ExecutiveQuestion,
    context: dict,
    assessment: models.DecisionAlignmentAssessment,
    role_analysis_outputs: dict[str, str],
    max_items: int = 4,
) -> list[models.ReasoningItem]:
    items: list[models.ReasoningItem] = []
    primary_decision_id = context["active_decisions"][0].id if context["active_decisions"] else None
    clean_challenge_points = [
        " ".join(point.strip().split())
        for point in assessment.challenge_points
        if point and point.strip()
    ]

    challenge_kind = (
        "objection" if assessment.alignment in {"potential_deviation", "likely_new_decision_required"} else "open_question"
    )
    for point in clean_challenge_points[:2]:
        items.append(
            models.ReasoningItem(
                question_id=panel_question.id,
                decision_id=primary_decision_id if challenge_kind == "objection" else None,
                kind=challenge_kind,
                content=point,
                source_type="panel",
                memory_level=_panel_reasoning_memory_level(
                    kind=challenge_kind,
                    decision_id=primary_decision_id if challenge_kind == "objection" else None,
                    alignment=assessment.alignment,
                ),
            )
        )

    analyst_text = role_analysis_outputs.get("analyst", "")
    if analyst_text and "risk" in analyst_text.lower() and "low visible tension" not in analyst_text.lower():
        items.append(
            models.ReasoningItem(
                question_id=panel_question.id,
                decision_id=primary_decision_id,
                kind="risk",
                content=analyst_text,
                source_type="panel",
                memory_level=_panel_reasoning_memory_level(
                    kind="risk",
                    decision_id=primary_decision_id,
                    alignment=assessment.alignment,
                ),
            )
        )

    strateg_text = role_analysis_outputs.get("strateg", "")
    if strateg_text and assessment.alignment in {"aligned", "potential_deviation", "likely_new_decision_required"}:
        items.append(
            models.ReasoningItem(
                question_id=panel_question.id,
                decision_id=primary_decision_id,
                kind="rationale",
                content=strateg_text,
                source_type="panel",
                memory_level=_panel_reasoning_memory_level(
                    kind="rationale",
                    decision_id=primary_decision_id,
                    alignment=assessment.alignment,
                ),
            )
        )

    merged_text = f"{analyst_text} {strateg_text}".lower()
    if "assumption" in merged_text:
        items.append(
            models.ReasoningItem(
                question_id=panel_question.id,
                decision_id=primary_decision_id,
                kind="assumption",
                content="Panel indicates assumptions should be explicitly verified before execution.",
                source_type="panel",
                memory_level=_panel_reasoning_memory_level(
                    kind="assumption",
                    decision_id=primary_decision_id,
                    alignment=assessment.alignment,
                ),
            )
        )

    if not items and assessment.alignment in {"potential_deviation", "likely_new_decision_required"}:
        fallback_content = clean_challenge_points[0] if clean_challenge_points else assessment.reason
        items.append(
            models.ReasoningItem(
                question_id=panel_question.id,
                decision_id=primary_decision_id,
                kind="objection",
                content=fallback_content,
                source_type="panel",
                memory_level=_panel_reasoning_memory_level(
                    kind="objection",
                    decision_id=primary_decision_id,
                    alignment=assessment.alignment,
                ),
            )
        )

    deduped: list[models.ReasoningItem] = []
    seen: set[tuple[str | None, str | None, str, str, str]] = set()
    for item in items:
        signature = _reasoning_signature(item)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def _build_decision_candidate_draft(
    *,
    question_text: str,
    topic: str,
    decision_mode: str | None,
    assessment_reason: str,
    challenge_points: list[str],
    formal_next_step: str,
    suggested_next_step_text: str,
    active_decision_ids: list[str],
    open_candidate_ids: list[str] | None = None,
) -> dict[str, str] | None:
    if decision_mode not in _DECISION_DRAFT_MODES:
        return None

    mode_label = (
        "exception/deviation" if decision_mode == "potential_deviation" else "new governing decision"
    )
    active_scope = ", ".join(active_decision_ids) if active_decision_ids else "none"
    clean_points = [
        " ".join(point.strip().split())
        for point in challenge_points
        if point and point.strip()
    ]
    key_challenge = clean_points[0] if clean_points else assessment_reason
    open_ids = ", ".join(open_candidate_ids or []) if open_candidate_ids else "none"

    return {
        "title": f"{topic}: decision update from panel question",
        "topic": topic,
        "candidate_text": (
            f"Question requires {mode_label}. "
            f"Define explicit decision scope before execution changes. "
            f"Question reference: {question_text}"
        ),
        "rationale": (
            f"Panel assessment: {assessment_reason} "
            f"| Active decision context: {active_scope} "
            f"| Key challenge: {key_challenge}"
        ),
        "manual_next_step": (
            f"Manual action: review open candidates for topic ({open_ids}); "
            f"if unresolved, create decision candidate with this draft. "
            f"Formal next step: {formal_next_step} "
            f"| Suggested next step: {suggested_next_step_text}"
        ),
    }


def _print_decision_candidate_draft(draft: dict[str, str] | None) -> None:
    if draft is None:
        return
    print("Decision candidate draft (manual):")
    print(f"- title: {draft['title']}")
    print(f"- topic: {draft['topic']}")
    print(f"- text: {draft['candidate_text']}")
    print(f"- rationale: {draft['rationale']}")
    print(f"- next: {draft['manual_next_step']}")


def _context_signal_line(context: dict) -> str:
    return (
        f"active={len(context['active_decisions'])} | "
        f"historical={len(context['historical_decisions'])} | "
        f"open_candidates={len(context['open_candidates'])} | "
        f"open_suggestions={len(context['open_suggestions'])}"
    )


def _reasoning_signal_line(reasoning_items: list[models.ReasoningItem]) -> str:
    if not reasoning_items:
        return "none"
    kind_counts = Counter(_REASONING_KIND_LABEL.get(item.kind, item.kind) for item in reasoning_items)
    visibility_counts = Counter(
        _REASONING_VISIBILITY_LABEL.get(item.memory_level, item.memory_level)
        for item in reasoning_items
    )
    kind_part = ", ".join(f"{kind} ({count})" for kind, count in sorted(kind_counts.items()))
    visibility_part = ", ".join(
        f"{level} ({count})" for level, count in sorted(visibility_counts.items())
    )
    return f"total={len(reasoning_items)} | kinds: {kind_part} | visibility: {visibility_part}"


def _sorted_reasoning_items(reasoning_items: list[models.ReasoningItem]) -> list[models.ReasoningItem]:
    return sorted(
        reasoning_items,
        key=lambda item: (
            _REASONING_KIND_PRIORITY.get(item.kind, 99),
            item.created_at,
        ),
    )


def _print_reasoning_item(item: models.ReasoningItem, include_question: bool = False) -> None:
    kind_label = _REASONING_KIND_LABEL.get(item.kind, item.kind.replace("_", " "))
    source_label = _REASONING_SOURCE_LABEL.get(item.source_type, item.source_type)
    visibility_label = _REASONING_VISIBILITY_LABEL.get(item.memory_level, item.memory_level)
    content = " ".join(item.content.split())
    print(f"- {kind_label}: {content}")
    meta = [source_label, visibility_label]
    if include_question and item.question_id:
        meta.append(f"question {item.question_id[:8]}")
    if item.decision_id:
        meta.append(f"decision {item.decision_id[:8]}")
    print("  " + " | ".join(meta))


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
    background: str | None = None,
    assumptions: str | None = None,
    risks: str | None = None,
    alternatives_considered: str | None = None,
    consequences: str | None = None,
    follow_up_notes: str | None = None,
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
            background=background,
            assumptions=assumptions,
            risks=risks,
            alternatives_considered=alternatives_considered,
            consequences=consequences,
            follow_up_notes=follow_up_notes,
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


def create_decision_candidate(
    db_path: str,
    session_id: str,
    title: str,
    topic: str,
    candidate_text: str,
    rationale: str | None = None,
    owner: str | None = None,
    tags: List[str] | None = None,
) -> models.DecisionCandidate:
    storage = Storage(db_path=db_path)
    try:
        session = storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' was not found")
        candidate = models.DecisionCandidate(
            session_id=session_id,
            title=title,
            topic=topic,
            candidate_text=candidate_text,
            rationale=rationale,
            owner=owner,
            tags=tags or [],
        )
        storage.add_decision_candidate(candidate)
        storage.add_session_event(
            models.SessionEvent(
                session_id=session_id,
                event_type="decision_candidate_created",
                message=f"Decision candidate '{candidate.id}' created: {candidate.title}",
            )
        )
        return candidate
    finally:
        storage.close()


def list_decision_candidates(
    db_path: str, session_id: str | None = None
) -> List[models.DecisionCandidate]:
    storage = Storage(db_path=db_path)
    try:
        if session_id:
            session = storage.get_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' was not found")
            return storage.list_decision_candidates_for_session(session_id)
        return storage.list_open_decision_candidates()
    finally:
        storage.close()


def confirm_decision_candidate(db_path: str, candidate_id: str) -> tuple[models.DecisionCandidate, models.Decision]:
    storage = Storage(db_path=db_path)
    try:
        candidate = storage.get_decision_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Decision candidate '{candidate_id}' was not found")
        if candidate.status != "proposed":
            raise ValueError(
                f"Decision candidate '{candidate_id}' is '{candidate.status}' and cannot be confirmed"
            )
    finally:
        storage.close()

    decision = create_decision(
        db_path=db_path,
        session_id=candidate.session_id,
        title=candidate.title,
        topic=candidate.topic,
        decision_text=candidate.candidate_text,
        rationale=candidate.rationale,
        owner=candidate.owner,
        tags=candidate.tags,
    )

    storage = Storage(db_path=db_path)
    try:
        storage.update_decision_candidate_status(candidate.id, "confirmed")
        storage.add_session_event(
            models.SessionEvent(
                session_id=candidate.session_id,
                event_type="decision_candidate_confirmed",
                message=f"Decision candidate '{candidate.id}' confirmed as decision '{decision.id}'",
            )
        )
        updated = storage.get_decision_candidate(candidate.id)
        if updated is None:
            raise ValueError(f"Decision candidate '{candidate_id}' was not found after update")
        return updated, decision
    finally:
        storage.close()


def dismiss_decision_candidate(db_path: str, candidate_id: str) -> models.DecisionCandidate:
    storage = Storage(db_path=db_path)
    try:
        candidate = storage.get_decision_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Decision candidate '{candidate_id}' was not found")
        if candidate.status != "proposed":
            raise ValueError(
                f"Decision candidate '{candidate_id}' is '{candidate.status}' and cannot be dismissed"
            )
        storage.update_decision_candidate_status(candidate.id, "dismissed")
        storage.add_session_event(
            models.SessionEvent(
                session_id=candidate.session_id,
                event_type="decision_candidate_dismissed",
                message=f"Decision candidate '{candidate.id}' dismissed",
            )
        )
        updated = storage.get_decision_candidate(candidate.id)
        if updated is None:
            raise ValueError(f"Decision candidate '{candidate_id}' was not found after update")
        return updated
    finally:
        storage.close()


def link_decisions(
    db_path: str,
    from_decision_id: str,
    to_decision_id: str,
    relation_type: str,
) -> models.DecisionLink:
    if relation_type not in _RELATION_TYPES:
        raise ValueError(
            f"Invalid relation type '{relation_type}'. Allowed values: {', '.join(sorted(_RELATION_TYPES))}"
        )
    if from_decision_id == to_decision_id:
        raise ValueError("A decision cannot be linked to itself")

    storage = Storage(db_path=db_path)
    try:
        source_decision = storage.get_decision(from_decision_id)
        if source_decision is None:
            raise ValueError(f"Source decision '{from_decision_id}' was not found")

        target_decision = storage.get_decision(to_decision_id)
        if target_decision is None:
            raise ValueError(f"Target decision '{to_decision_id}' was not found")

        link = models.DecisionLink(
            from_decision_id=from_decision_id,
            to_decision_id=to_decision_id,
            relation_type=relation_type,
        )
        try:
            storage.add_decision_link(link)
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "Decision link already exists for this source, target, and relation type"
            ) from exc

        if relation_type == "supersedes":
            storage.update_decision_status(to_decision_id, "superseded")

        message = (
            f"Decision link created: {relation_type} "
            f"source={from_decision_id} target={to_decision_id}"
        )
        storage.add_session_event(
            models.SessionEvent(
                session_id=source_decision.session_id,
                event_type="decision_link_created",
                message=message,
            )
        )
        if source_decision.session_id != target_decision.session_id:
            storage.add_session_event(
                models.SessionEvent(
                    session_id=target_decision.session_id,
                    event_type="decision_link_created",
                    message=message,
                )
            )
        return link
    finally:
        storage.close()


def list_decision_links(db_path: str, decision_id: str) -> List[models.DecisionLink]:
    storage = Storage(db_path=db_path)
    try:
        decision = storage.get_decision(decision_id)
        if decision is None:
            raise ValueError(f"Decision '{decision_id}' was not found")
        return storage.list_links_for_decision(decision_id)
    finally:
        storage.close()


def show_decision(
    db_path: str, decision_id: str
) -> tuple[
    models.Decision,
    List[models.DecisionLink],
    List[models.DecisionLink],
    List[models.ReasoningItem],
]:
    storage = Storage(db_path=db_path)
    try:
        decision = storage.get_decision(decision_id)
        if decision is None:
            raise ValueError(f"Decision '{decision_id}' was not found")
        outgoing_links = storage.list_outgoing_links(decision_id)
        incoming_links = storage.list_incoming_links(decision_id)
        reasoning_items = storage.list_reasoning_items_for_decision(decision_id)
        return decision, outgoing_links, incoming_links, reasoning_items
    finally:
        storage.close()


def suggest_decision_links(db_path: str, decision_id: str) -> List[models.DecisionSuggestion]:
    storage = Storage(db_path=db_path)
    try:
        source_decision = storage.get_decision(decision_id)
        if source_decision is None:
            raise ValueError(f"Decision '{decision_id}' was not found")

        created: List[models.DecisionSuggestion] = []
        for target_decision in storage.list_active_decisions():
            if target_decision.id == source_decision.id:
                continue
            if target_decision.topic != source_decision.topic:
                continue

            candidates = [
                (
                    "related_decision",
                    f"Decisions share topic '{source_decision.topic}'.",
                )
            ]
            if target_decision.decision_text != source_decision.decision_text:
                candidates.append(
                    (
                        "possible_supersedes",
                        f"Decisions share topic '{source_decision.topic}' but have different decision text.",
                    )
                )

            for suggestion_type, reason in candidates:
                suggestion = models.DecisionSuggestion(
                    source_decision_id=source_decision.id,
                    target_decision_id=target_decision.id,
                    suggestion_type=suggestion_type,
                    reason=reason,
                )
                try:
                    storage.add_decision_suggestion(suggestion)
                except sqlite3.IntegrityError:
                    continue
                _add_suggestion_event(
                    storage=storage,
                    source_decision=source_decision,
                    target_decision=target_decision,
                    event_type="decision_suggestion_created",
                    message=(
                        f"Decision suggestion '{suggestion.id}' created: {suggestion.suggestion_type} "
                        f"source={suggestion.source_decision_id} target={suggestion.target_decision_id}"
                    ),
                )
                created.append(suggestion)
        return created
    finally:
        storage.close()


def list_decision_suggestions(
    db_path: str, decision_id: str | None = None
) -> List[models.DecisionSuggestion]:
    storage = Storage(db_path=db_path)
    try:
        if decision_id:
            decision = storage.get_decision(decision_id)
            if decision is None:
                raise ValueError(f"Decision '{decision_id}' was not found")
            return storage.list_suggestions_for_decision(decision_id)
        return storage.list_open_suggestions()
    finally:
        storage.close()


def accept_decision_suggestion(
    db_path: str, suggestion_id: str
) -> tuple[models.DecisionSuggestion, models.DecisionLink]:
    storage = Storage(db_path=db_path)
    try:
        suggestion = storage.get_decision_suggestion(suggestion_id)
        if suggestion is None:
            raise ValueError(f"Decision suggestion '{suggestion_id}' was not found")
        if suggestion.status != "open":
            raise ValueError(
                f"Decision suggestion '{suggestion_id}' is '{suggestion.status}' and cannot be accepted"
            )
        source_decision = storage.get_decision(suggestion.source_decision_id)
        target_decision = storage.get_decision(suggestion.target_decision_id)
        if source_decision is None:
            raise ValueError(f"Source decision '{suggestion.source_decision_id}' was not found")
        if target_decision is None:
            raise ValueError(f"Target decision '{suggestion.target_decision_id}' was not found")
    finally:
        storage.close()

    relation_type = _AUTO_LINKABLE_SUGGESTIONS.get(suggestion.suggestion_type)
    if relation_type is None:
        raise ValueError(
            f"Suggestion type '{suggestion.suggestion_type}' cannot be auto-accepted yet"
        )
    link = link_decisions(
        db_path=db_path,
        from_decision_id=suggestion.source_decision_id,
        to_decision_id=suggestion.target_decision_id,
        relation_type=relation_type,
    )

    storage = Storage(db_path=db_path)
    try:
        storage.update_decision_suggestion_status(suggestion.id, "accepted")
        _add_suggestion_event(
            storage=storage,
            source_decision=source_decision,
            target_decision=target_decision,
            event_type="decision_suggestion_accepted",
            message=(
                f"Decision suggestion '{suggestion.id}' accepted: {suggestion.suggestion_type} "
                f"source={suggestion.source_decision_id} target={suggestion.target_decision_id}"
            ),
        )
        updated = storage.get_decision_suggestion(suggestion.id)
        if updated is None:
            raise ValueError(f"Decision suggestion '{suggestion_id}' was not found after update")
        return updated, link
    finally:
        storage.close()


def dismiss_decision_suggestion(db_path: str, suggestion_id: str) -> models.DecisionSuggestion:
    storage = Storage(db_path=db_path)
    try:
        suggestion = storage.get_decision_suggestion(suggestion_id)
        if suggestion is None:
            raise ValueError(f"Decision suggestion '{suggestion_id}' was not found")
        if suggestion.status != "open":
            raise ValueError(
                f"Decision suggestion '{suggestion_id}' is '{suggestion.status}' and cannot be dismissed"
            )
        source_decision = storage.get_decision(suggestion.source_decision_id)
        target_decision = storage.get_decision(suggestion.target_decision_id)
        if source_decision is None:
            raise ValueError(f"Source decision '{suggestion.source_decision_id}' was not found")
        if target_decision is None:
            raise ValueError(f"Target decision '{suggestion.target_decision_id}' was not found")
        storage.update_decision_suggestion_status(suggestion.id, "dismissed")
        _add_suggestion_event(
            storage=storage,
            source_decision=source_decision,
            target_decision=target_decision,
            event_type="decision_suggestion_dismissed",
            message=(
                f"Decision suggestion '{suggestion.id}' dismissed: {suggestion.suggestion_type} "
                f"source={suggestion.source_decision_id} target={suggestion.target_decision_id}"
            ),
        )
        updated = storage.get_decision_suggestion(suggestion.id)
        if updated is None:
            raise ValueError(f"Decision suggestion '{suggestion_id}' was not found after update")
        return updated
    finally:
        storage.close()


def ask_decision_panel(
    db_path: str,
    question: str,
    topic: str,
    session_id: str | None = None,
    llm_provider: LLMProvider | None = None,
) -> tuple[
    models.ExecutiveQuestion,
    dict,
    models.DecisionAlignmentAssessment,
    list[models.PanelResponse],
    str,
    str,
    str,
]:
    normalized_question = question.strip()
    normalized_topic = topic.strip()
    if not normalized_question:
        raise ValueError("Question cannot be empty")
    if not normalized_topic:
        raise ValueError("Topic is required")

    storage = Storage(db_path=db_path)
    try:
        if session_id:
            session = storage.get_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' was not found")
        panel_question = models.ExecutiveQuestion(
            question_text=normalized_question,
            topic=normalized_topic,
            session_id=session_id,
        )
        storage.add_panel_question(panel_question)
        context = build_context_packet(storage, topic=normalized_topic, session_id=session_id)
        assessment = assess_question_against_active_decisions(
            normalized_question, context["active_decisions"]
        )

        roles = active_advisor_roles(default_advisor_roles())
        heuristic_role_outputs = per_role_analysis(
            question=normalized_question,
            context=context,
            assessment=assessment,
            roles=roles,
        )
        resolved_provider = llm_provider or provider_from_env()
        provider_enabled = (
            provider_enabled_from_env()
            if llm_provider is None
            else resolved_provider.name != "heuristic"
        )
        role_analysis_outputs, role_sources, fallback_reasons = apply_role_llm_overrides(
            provider=resolved_provider,
            roles=roles,
            question=normalized_question,
            context=context,
            assessment=assessment,
            heuristic_outputs=heuristic_role_outputs,
        )
        llm_status = {
            "provider": resolved_provider.name,
            "model": getattr(resolved_provider, "model", None),
            "provider_enabled": provider_enabled,
            "provider_available": resolved_provider.is_available(),
            "role_sources": role_sources,
            "llm_roles": [role for role, source in role_sources.items() if source == "llm"],
            "fallback_roles": [role for role, source in role_sources.items() if source != "llm"],
            "fallback_reasons": fallback_reasons,
        }
        responses = [
                models.PanelResponse(
                    question_id=panel_question.id,
                    agent_name=role.name,
                    response_text=role_analysis_outputs[role.name],
                )
                for role in roles
                if role.name in role_analysis_outputs
            ]
        storage.add_panel_responses(responses)
        storage.set_panel_question_context_decisions(
            panel_question.id,
            [decision.id for decision in context["active_decisions"]],
        )

        combined = combined_recommendation(
            normalized_question,
            context,
            assessment,
            role_analysis=role_analysis_outputs,
        )
        panel_outcome = build_panel_outcome(context, assessment)
        likely_new_decision = panel_outcome.likely_requires_new_decision
        next_step = suggested_next_step(normalized_question, context, assessment)
        sections = build_panel_sections(
                question=normalized_question,
                context=context,
                assessment=assessment,
                per_role_analysis=role_analysis_outputs,
                combined=combined,
                panel_outcome=panel_outcome,
                suggested_formal_step=next_step,
                llm_status=llm_status,
            )
        storage.add_panel_question_analysis(
            models.ExecutiveQuestionAnalysis(
                question_id=panel_question.id,
                assessment_alignment=assessment.alignment,
                assessment_reason=assessment.reason,
                challenge_points=assessment.challenge_points,
                combined_recommendation=combined,
                suggested_next_step=next_step,
                likely_requires_new_decision=likely_new_decision,
                question_interpretation=sections["question_interpretation"],
                relevant_context=sections["relevant_context"],
                per_role_analysis=sections["per_role_analysis"],
                tensions=sections["tensions"],
                decision_status_assessment=sections["decision_status_assessment"],
            )
        )
        existing_signatures = {
            _reasoning_signature(item)
            for item in storage.list_reasoning_items_for_question(panel_question.id)
        }
        for item in _build_reasoning_items_from_panel(
            panel_question=panel_question,
            context=context,
            assessment=assessment,
            role_analysis_outputs=role_analysis_outputs,
        ):
            signature = _reasoning_signature(item)
            if signature in existing_signatures:
                continue
            storage.add_reasoning_item(item)
            existing_signatures.add(signature)
        return panel_question, context, assessment, responses, combined, likely_new_decision, next_step
    finally:
        storage.close()


def show_panel_question_case(db_path: str, question_id: str) -> dict:
    storage = Storage(db_path=db_path)
    try:
        case = storage.get_panel_question_case(question_id)
        if case is None:
            raise ValueError(f"Panel question '{question_id}' was not found")
        return case
    finally:
        storage.close()


def list_panel_questions(
    db_path: str,
    session_id: str | None = None,
    topic: str | None = None,
    limit: int = 20,
) -> List[models.ExecutiveQuestion]:
    storage = Storage(db_path=db_path)
    try:
        if session_id:
            session = storage.get_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' was not found")
        return storage.list_panel_questions(session_id=session_id, topic=topic, limit=limit)
    finally:
        storage.close()


def _truncate_question(text: str, max_length: int = 90) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip() + "..."


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


def alpha_demo_setup(
    db_path: str,
    session_name: str = "Alpha Demo Session",
    topic: str = "Expansion",
    question: str = "Ska vi öppna Danmark ändå trots att Norge är försenat?",
) -> dict[str, object]:
    session = create_session(db_path=db_path, session_name=session_name)
    active_decision = create_decision(
        db_path=db_path,
        session_id=session.id,
        title="Nordic rollout sequence",
        topic=topic,
        decision_text="Open Denmark only after Norway is stable.",
        rationale="Minimize rollout risk and operational instability.",
        owner="leadership",
        tags=["alpha-demo", "active-direction"],
    )
    storage = Storage(db_path=db_path)
    try:
        storage.add_decision(
            models.Decision(
                session_id=session.id,
                title="Earlier expansion baseline",
                topic=topic,
                decision_text="Move in parallel across all markets.",
                rationale="Legacy baseline kept for history in demo.",
                status="superseded",
                owner="leadership",
                tags=["alpha-demo", "history"],
            )
        )
    finally:
        storage.close()
    candidate = create_decision_candidate(
        db_path=db_path,
        session_id=session.id,
        title="Potential deviation candidate",
        topic=topic,
        candidate_text="Allow Denmark launch before Norway stabilization as an explicit exception.",
        rationale="Commercial pressure may justify a controlled exception.",
        owner="governance",
        tags=["alpha-demo", "candidate"],
    )
    panel_question, context, assessment, responses, combined, likely_new_decision, next_step = ask_decision_panel(
        db_path=db_path,
        question=question,
        topic=topic,
        session_id=session.id,
    )
    return {
        "session": session,
        "active_decision": active_decision,
        "candidate": candidate,
        "panel_question": panel_question,
        "context": context,
        "assessment": assessment,
        "responses": responses,
        "combined": combined,
        "likely_new_decision": likely_new_decision,
        "next_step": next_step,
    }


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
    create_decision_parser.add_argument("--background", help="Optional background context.")
    create_decision_parser.add_argument("--assumptions", help="Optional assumptions.")
    create_decision_parser.add_argument("--risks", help="Optional risks.")
    create_decision_parser.add_argument(
        "--alternatives-considered",
        dest="alternatives_considered",
        help="Optional alternatives considered.",
    )
    create_decision_parser.add_argument("--consequences", help="Optional consequences.")
    create_decision_parser.add_argument("--follow-up-notes", dest="follow_up_notes", help="Optional follow-up notes.")
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

    create_candidate_parser = subparsers.add_parser(
        "create-decision-candidate", help="Create a decision candidate for a session."
    )
    create_candidate_parser.add_argument("--session-id", required=True, help="Session id.")
    create_candidate_parser.add_argument("--title", required=True, help="Candidate title.")
    create_candidate_parser.add_argument("--topic", required=True, help="Candidate topic.")
    create_candidate_parser.add_argument("--text", dest="candidate_text", required=True, help="Candidate text.")
    create_candidate_parser.add_argument("--rationale", help="Optional rationale.")
    create_candidate_parser.add_argument("--owner", help="Optional owner.")
    create_candidate_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Candidate tag. Repeat --tag for multiple values.",
    )

    list_candidates_parser = subparsers.add_parser("list-decision-candidates", help="List decision candidates.")
    list_candidates_parser.add_argument("--session-id", help="Optional session id.")

    confirm_candidate_parser = subparsers.add_parser(
        "confirm-decision-candidate", help="Confirm a proposed decision candidate."
    )
    confirm_candidate_parser.add_argument("--candidate-id", required=True, help="Candidate id.")

    dismiss_candidate_parser = subparsers.add_parser(
        "dismiss-decision-candidate", help="Dismiss a proposed decision candidate."
    )
    dismiss_candidate_parser.add_argument("--candidate-id", required=True, help="Candidate id.")

    link_decisions_parser = subparsers.add_parser("link-decisions", help="Create an explicit link between decisions.")
    link_decisions_parser.add_argument("--from-decision-id", required=True, help="Source/newer decision id.")
    link_decisions_parser.add_argument("--to-decision-id", required=True, help="Target/older decision id.")
    link_decisions_parser.add_argument(
        "--relation-type",
        required=True,
        choices=sorted(_RELATION_TYPES),
        help="Type of relation between source and target decisions.",
    )

    list_links_parser = subparsers.add_parser("list-decision-links", help="List links for a decision.")
    list_links_parser.add_argument("--decision-id", required=True, help="Decision id.")

    show_decision_parser = subparsers.add_parser("show-decision", help="Show decision details and related links.")
    show_decision_parser.add_argument("--decision-id", required=True, help="Decision id.")

    suggest_links_parser = subparsers.add_parser(
        "suggest-decision-links", help="Generate heuristic link suggestions for a decision."
    )
    suggest_links_parser.add_argument("--decision-id", required=True, help="Decision id to evaluate.")

    list_suggestions_parser = subparsers.add_parser("list-decision-suggestions", help="List decision suggestions.")
    list_suggestions_parser.add_argument("--decision-id", help="Optional decision id.")

    accept_suggestion_parser = subparsers.add_parser(
        "accept-decision-suggestion", help="Accept an open decision suggestion."
    )
    accept_suggestion_parser.add_argument("--suggestion-id", required=True, help="Suggestion id.")

    dismiss_suggestion_parser = subparsers.add_parser(
        "dismiss-decision-suggestion", help="Dismiss an open decision suggestion."
    )
    dismiss_suggestion_parser.add_argument("--suggestion-id", required=True, help="Suggestion id.")

    ask_panel_parser = subparsers.add_parser("ask-decision-panel", help="Ask the leadership decision support panel.")
    ask_panel_parser.add_argument("--question", required=True, help="Leadership panel question.")
    ask_panel_parser.add_argument("--topic", required=True, help="Decision topic.")
    ask_panel_parser.add_argument("--session-id", help="Optional session scope.")

    show_panel_question_parser = subparsers.add_parser(
        "show-panel-question", help="Show a previously stored panel question and analysis."
    )
    show_panel_question_parser.add_argument("--question-id", required=True, help="Panel question id.")

    list_panel_questions_parser = subparsers.add_parser(
        "list-panel-questions", help="List previously asked panel questions."
    )
    list_panel_questions_parser.add_argument("--session-id", help="Optional session id filter.")
    list_panel_questions_parser.add_argument("--topic", help="Optional topic filter.")
    list_panel_questions_parser.add_argument("--limit", type=int, default=20, help="Maximum number of questions.")

    alpha_demo_parser = subparsers.add_parser(
        "alpha-demo-setup",
        help="Seed a minimal alpha demo dataset and run one panel question.",
    )
    alpha_demo_parser.add_argument(
        "--session-name",
        default="Alpha Demo Session",
        help="Session name for seeded demo data.",
    )
    alpha_demo_parser.add_argument("--topic", default="Expansion", help="Topic for seeded demo data.")
    alpha_demo_parser.add_argument(
        "--question",
        default="Ska vi öppna Danmark ändå trots att Norge är försenat?",
        help="Panel question to run for the demo seed.",
    )

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
                background=args.background,
                assumptions=args.assumptions,
                risks=args.risks,
                alternatives_considered=args.alternatives_considered,
                consequences=args.consequences,
                follow_up_notes=args.follow_up_notes,
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

    if args.command == "create-decision-candidate":
        try:
            candidate = create_decision_candidate(
                db_path=args.db_path,
                session_id=args.session_id,
                title=args.title,
                topic=args.topic,
                candidate_text=args.candidate_text,
                rationale=args.rationale,
                owner=args.owner,
                tags=args.tags,
            )
        except ValueError as exc:
            print(f"Decision candidate creation failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Created decision candidate: {candidate.id}")
        print(f"Session: {candidate.session_id}")
        print(f"Title: {candidate.title}")
        print(f"Topic: {candidate.topic}")
        print(f"Status: {candidate.status}")
        print(f"Tags: {', '.join(candidate.tags) if candidate.tags else '-'}")
        return

    if args.command == "list-decision-candidates":
        try:
            candidates = list_decision_candidates(args.db_path, session_id=args.session_id)
        except ValueError as exc:
            print(f"Decision candidate listing failed: {exc}")
            raise SystemExit(1) from exc
        scope = args.session_id if args.session_id else "all proposed"
        print(f"Decision candidates ({scope}): {len(candidates)}")
        for candidate in candidates:
            print(
                f"- {candidate.id} [{candidate.status}] session={candidate.session_id} topic={candidate.topic} title={candidate.title}"
            )
            print(f"  {candidate.candidate_text}")
        return

    if args.command == "confirm-decision-candidate":
        try:
            candidate, decision = confirm_decision_candidate(args.db_path, args.candidate_id)
        except ValueError as exc:
            print(f"Decision candidate confirmation failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Confirmed decision candidate: {candidate.id}")
        print(f"Candidate status: {candidate.status}")
        print(f"Created decision: {decision.id}")
        return

    if args.command == "dismiss-decision-candidate":
        try:
            candidate = dismiss_decision_candidate(args.db_path, args.candidate_id)
        except ValueError as exc:
            print(f"Decision candidate dismissal failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Dismissed decision candidate: {candidate.id}")
        print(f"Candidate status: {candidate.status}")
        return

    if args.command == "link-decisions":
        try:
            link = link_decisions(
                db_path=args.db_path,
                from_decision_id=args.from_decision_id,
                to_decision_id=args.to_decision_id,
                relation_type=args.relation_type,
            )
        except ValueError as exc:
            print(f"Decision linking failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Created decision link: {link.id}")
        print(f"Relation: {link.relation_type}")
        print(f"From decision: {link.from_decision_id}")
        print(f"To decision: {link.to_decision_id}")
        return

    if args.command == "list-decision-links":
        try:
            links = list_decision_links(args.db_path, args.decision_id)
        except ValueError as exc:
            print(f"Decision link listing failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Decision links ({args.decision_id}): {len(links)}")
        for link in links:
            print(f"- {link.id} [{link.relation_type}] {link.from_decision_id} -> {link.to_decision_id}")
        return

    if args.command == "show-decision":
        try:
            decision, outgoing_links, incoming_links, reasoning_items = show_decision(
                args.db_path, args.decision_id
            )
        except ValueError as exc:
            print(f"Decision show failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Decision: {decision.id}")
        print(f"Session: {decision.session_id}")
        print(f"Title: {decision.title}")
        print(f"Topic: {decision.topic}")
        print(f"Status: {decision.status}")
        print(f"Owner: {decision.owner or '-'}")
        print(f"Tags: {', '.join(decision.tags) if decision.tags else '-'}")
        print(f"Text: {decision.decision_text}")
        print(f"Rationale: {decision.rationale or '-'}")
        print(f"Background: {decision.background or '-'}")
        print(f"Assumptions: {decision.assumptions or '-'}")
        print(f"Risks: {decision.risks or '-'}")
        print(f"Alternatives considered: {decision.alternatives_considered or '-'}")
        print(f"Consequences: {decision.consequences or '-'}")
        print(f"Follow-up notes: {decision.follow_up_notes or '-'}")
        print(f"Key reasoning notes: {len(reasoning_items)}")
        for item in _sorted_reasoning_items(reasoning_items):
            _print_reasoning_item(item, include_question=True)
        print(f"Outgoing links: {len(outgoing_links)}")
        for link in outgoing_links:
            print(f"- {link.id} [{link.relation_type}] {link.from_decision_id} -> {link.to_decision_id}")
        print(f"Incoming links: {len(incoming_links)}")
        for link in incoming_links:
            print(f"- {link.id} [{link.relation_type}] {link.from_decision_id} -> {link.to_decision_id}")
        return

    if args.command == "suggest-decision-links":
        try:
            suggestions = suggest_decision_links(args.db_path, args.decision_id)
        except ValueError as exc:
            print(f"Decision suggestion generation failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Created decision suggestions: {len(suggestions)}")
        for suggestion in suggestions:
            print(
                f"- {suggestion.id} [{suggestion.suggestion_type}] "
                f"{suggestion.source_decision_id} -> {suggestion.target_decision_id}"
            )
            print(f"  reason: {suggestion.reason}")
        return

    if args.command == "list-decision-suggestions":
        try:
            suggestions = list_decision_suggestions(args.db_path, decision_id=args.decision_id)
        except ValueError as exc:
            print(f"Decision suggestion listing failed: {exc}")
            raise SystemExit(1) from exc
        scope = args.decision_id if args.decision_id else "all open"
        print(f"Decision suggestions ({scope}): {len(suggestions)}")
        for suggestion in suggestions:
            print(
                f"- {suggestion.id} [{suggestion.status}/{suggestion.suggestion_type}] "
                f"{suggestion.source_decision_id} -> {suggestion.target_decision_id}"
            )
            print(f"  reason: {suggestion.reason}")
        return

    if args.command == "accept-decision-suggestion":
        try:
            suggestion, link = accept_decision_suggestion(args.db_path, args.suggestion_id)
        except ValueError as exc:
            print(f"Decision suggestion accept failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Accepted decision suggestion: {suggestion.id}")
        print(f"Suggestion status: {suggestion.status}")
        print(f"Created decision link: {link.id}")
        print(f"Relation: {link.relation_type}")
        return

    if args.command == "dismiss-decision-suggestion":
        try:
            suggestion = dismiss_decision_suggestion(args.db_path, args.suggestion_id)
        except ValueError as exc:
            print(f"Decision suggestion dismissal failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Dismissed decision suggestion: {suggestion.id}")
        print(f"Suggestion status: {suggestion.status}")
        return

    if args.command == "ask-decision-panel":
        try:
            panel_question, context, assessment, responses, combined, likely_new_decision, next_step = ask_decision_panel(
                db_path=args.db_path,
                question=args.question,
                topic=args.topic,
                session_id=args.session_id,
            )
        except ValueError as exc:
            print(f"Decision panel failed: {exc}")
            raise SystemExit(1) from exc

        by_agent = {response.agent_name: response.response_text for response in responses}
        stored_analysis = show_panel_question_case(args.db_path, panel_question.id).get("analysis")
        status_payload = stored_analysis.decision_status_assessment if stored_analysis else {}
        llm_status = (
            status_payload.get("llm_status", {})
            if isinstance(status_payload, dict)
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
        provider_name = llm_status.get("provider", "heuristic") if isinstance(llm_status, dict) else "heuristic"
        provider_model = llm_status.get("model") if isinstance(llm_status, dict) else None
        provider_enabled = bool(llm_status.get("provider_enabled")) if isinstance(llm_status, dict) else False
        provider_available = bool(llm_status.get("provider_available")) if isinstance(llm_status, dict) else False
        print(f"Question: {panel_question.question_text}")
        print(f"Topic: {panel_question.topic}")

        print("Active decisions in scope:")
        if context["active_decisions"]:
            for decision in context["active_decisions"]:
                print(f"- {decision.id} title={decision.title}")
        else:
            print("- none")

        print("Previous related decisions:")
        if context["historical_decisions"]:
            for decision in context["historical_decisions"]:
                print(f"- {decision.id} title={decision.title}")
        else:
            print("- none")

        print("Pending decision candidates:")
        if context["open_candidates"]:
            for candidate in context["open_candidates"]:
                print(f"- {candidate.id} title={candidate.title}")
        else:
            print("- none")

        print("Pending decision suggestions:")
        if context["open_suggestions"]:
            for suggestion in context["open_suggestions"]:
                print(
                    f"- {suggestion.id} [{suggestion.suggestion_type}] "
                    f"{suggestion.source_decision_id} -> {suggestion.target_decision_id}"
                )
        else:
            print("- none")

        print(f"Assessment: {alignment_label(assessment.alignment)} ({assessment.reason})")
        outcome = build_panel_outcome(context, assessment)
        print(f"Handling mode: {decision_mode_label(outcome.decision_mode)}")
        print(f"Formal next step: {outcome.formal_next_step}")
        print(
            "Decision summary: "
            f"Assessment: {alignment_label(assessment.alignment)} | "
            f"Mode: {decision_mode_label(outcome.decision_mode)} | "
            f"New decision likelihood: {likelihood_label(likely_new_decision)}"
        )
        print(
            "Role generation mode: "
            f"provider={provider_name}"
            f"{f' ({provider_model})' if provider_model else ''} | enabled={'yes' if provider_enabled else 'no'} | "
            f"available={'yes' if provider_available else 'no'}"
        )
        if fallback_reasons:
            compact = ", ".join(f"{role}={reason}" for role, reason in sorted(fallback_reasons.items()))
            print(f"Fallback notes: {compact}")
        print(f"Decision context at a glance: {_context_signal_line(context)}")
        draft = _build_decision_candidate_draft(
            question_text=panel_question.question_text,
            topic=panel_question.topic,
            decision_mode=outcome.decision_mode,
            assessment_reason=assessment.reason,
            challenge_points=assessment.challenge_points,
            formal_next_step=outcome.formal_next_step,
            suggested_next_step_text=next_step,
            active_decision_ids=[decision.id for decision in context["active_decisions"]],
            open_candidate_ids=[candidate.id for candidate in context["open_candidates"]],
        )
        _print_decision_candidate_draft(draft)
        print("Key concerns:")
        if assessment.challenge_points:
            for point in assessment.challenge_points:
                print(f"- {point}")
        else:
            print("- none")

        print(
            f"Strateg [{_role_response_source_label(role_sources.get('strateg', 'heuristic'))}]: "
            f"{by_agent['strateg']}"
        )
        print(
            f"Analyst [{_role_response_source_label(role_sources.get('analyst', 'heuristic'))}]: "
            f"{by_agent['analyst']}"
        )
        print(
            f"Operator [{_role_response_source_label(role_sources.get('operator', 'heuristic'))}]: "
            f"{by_agent['operator']}"
        )
        print(
            f"Governance [{_role_response_source_label(role_sources.get('governance', 'heuristic'))}]: "
            f"{by_agent['governance']}"
        )
        print(f"Combined recommendation: {combined}")
        print(f"New decision likely?: {likelihood_label(likely_new_decision)}")
        print(f"Recommended next step: {next_step}")
        print(f"Saved question id: {panel_question.id}")
        print("Next steps:")
        print(
            f"- python src/main.py --db-path {args.db_path} "
            f"show-panel-question --question-id {panel_question.id}"
        )
        print(
            f"- python src/main.py --db-path {args.db_path} "
            f"list-panel-questions --topic {panel_question.topic}"
        )
        print(f"- python src/main.py --db-path {args.db_path} tui")
        return

    if args.command == "show-panel-question":
        try:
            case = show_panel_question_case(args.db_path, args.question_id)
        except ValueError as exc:
            print(f"Panel question lookup failed: {exc}")
            raise SystemExit(1) from exc

        question = case["question"]
        analysis = case["analysis"]
        sections = case.get("sections", {}) or {}
        responses = case["responses"]
        context_decision_ids = case["context_decision_ids"]
        reasoning_items = case.get("reasoning_items", [])
        by_agent = {response.agent_name: response.response_text for response in responses}
        role_sources: dict[str, str] = {}
        fallback_reasons: dict[str, str] = {}
        provider_name = "heuristic"
        provider_model = None
        provider_enabled = False
        provider_available = False

        print(f"Question: {question.question_text}")
        print(f"Topic: {question.topic}")
        print(f"Status: {question.status}")
        print(
            "Active decision references: "
            + (", ".join(context_decision_ids) if context_decision_ids else "none")
        )
        if analysis is not None:
            assessment_payload = analysis.decision_status_assessment or {}
            llm_status = (
                assessment_payload.get("llm_status", {})
                if isinstance(assessment_payload, dict)
                else {}
            )
            if isinstance(llm_status, dict):
                role_sources = llm_status.get("role_sources", {}) or {}
                fallback_reasons = llm_status.get("fallback_reasons", {}) or {}
                provider_name = llm_status.get("provider", "heuristic")
                provider_model = llm_status.get("model")
                provider_enabled = bool(llm_status.get("provider_enabled"))
                provider_available = bool(llm_status.get("provider_available"))
            formal_next_step_text = assessment_payload.get("formal_next_step", analysis.suggested_next_step)
            print(
                f"Assessment: "
                f"{alignment_label(analysis.assessment_alignment)} ({analysis.assessment_reason})"
            )
            decision_mode = assessment_payload.get("decision_mode", "-")
            print(
                f"Handling mode: "
                f"{decision_mode_label(decision_mode) if decision_mode != '-' else '-'}"
            )
            print(f"Formal next step: {formal_next_step_text}")
            print(
                "Decision summary: "
                f"Assessment: {alignment_label(analysis.assessment_alignment)} | "
                f"Mode: {decision_mode_label(decision_mode) if decision_mode != '-' else '-'} | "
                f"New decision likelihood: {likelihood_label(analysis.likely_requires_new_decision)}"
            )
            print(
                "Role generation mode: "
                f"provider={provider_name}"
                f"{f' ({provider_model})' if provider_model else ''} | enabled={'yes' if provider_enabled else 'no'} | "
                f"available={'yes' if provider_available else 'no'}"
            )
            if fallback_reasons:
                compact = ", ".join(f"{role}={reason}" for role, reason in sorted(fallback_reasons.items()))
                print(f"Fallback notes: {compact}")
            relevant_context = sections.get("relevant_context", {})
            active_ids = relevant_context.get("active_decision_ids", []) if isinstance(relevant_context, dict) else []
            historical_ids = (
                relevant_context.get("historical_decision_ids", [])
                if isinstance(relevant_context, dict)
                else []
            )
            open_candidate_ids = (
                relevant_context.get("open_candidate_ids", [])
                if isinstance(relevant_context, dict)
                else []
            )
            open_suggestion_ids = (
                relevant_context.get("open_suggestion_ids", [])
                if isinstance(relevant_context, dict)
                else []
            )
            print(
                "Decision context at a glance: "
                f"active={len(active_ids or context_decision_ids)} | "
                f"historical={len(historical_ids)} | "
                f"open_candidates={len(open_candidate_ids)} | "
                f"open_suggestions={len(open_suggestion_ids)}"
            )
            draft = _build_decision_candidate_draft(
                question_text=question.question_text,
                topic=question.topic,
                decision_mode=assessment_payload.get("decision_mode"),
                assessment_reason=analysis.assessment_reason,
                challenge_points=analysis.challenge_points,
                formal_next_step=formal_next_step_text,
                suggested_next_step_text=analysis.suggested_next_step,
                active_decision_ids=context_decision_ids,
            )
            _print_decision_candidate_draft(draft)
            print(
                "Key concerns: "
                + (" | ".join(analysis.challenge_points) if analysis.challenge_points else "none")
            )
            print(f"Combined recommendation: {analysis.combined_recommendation}")
            print(f"New decision likely?: {likelihood_label(analysis.likely_requires_new_decision)}")
            print(f"Recommended next step: {analysis.suggested_next_step}")
        else:
            print("Assessment: none")
            print("Key concerns: none")
            print("Combined recommendation: none")
            print("New decision likely?: Probably")
            print("Recommended next step: none")
        print(
            f"Strateg [{_role_response_source_label(role_sources.get('strateg', 'heuristic'))}]: "
            f"{by_agent.get('strateg', '-')}"
        )
        print(
            f"Analyst [{_role_response_source_label(role_sources.get('analyst', 'heuristic'))}]: "
            f"{by_agent.get('analyst', '-')}"
        )
        print(
            f"Operator [{_role_response_source_label(role_sources.get('operator', 'heuristic'))}]: "
            f"{by_agent.get('operator', '-')}"
        )
        print(
            f"Governance [{_role_response_source_label(role_sources.get('governance', 'heuristic'))}]: "
            f"{by_agent.get('governance', '-')}"
        )
        print(f"Key reasoning notes: {len(reasoning_items)}")
        print(f"Reasoning summary: {_reasoning_signal_line(reasoning_items)}")
        for item in _sorted_reasoning_items(reasoning_items):
            _print_reasoning_item(item)
        print("Next steps:")
        print(
            f"- python src/main.py --db-path {args.db_path} "
            f"ask-decision-panel --topic {question.topic} --question \"<din nästa fråga>\""
        )
        print(f"- python src/main.py --db-path {args.db_path} tui")
        return

    if args.command == "list-panel-questions":
        try:
            questions = list_panel_questions(
                db_path=args.db_path,
                session_id=args.session_id,
                topic=args.topic,
                limit=args.limit,
            )
        except ValueError as exc:
            print(f"Panel question listing failed: {exc}")
            raise SystemExit(1) from exc
        print(f"Panel questions: {len(questions)}")
        for question in questions:
            print(
                f"- {question.id} [{question.status}] "
                f"created_at={question.created_at.isoformat()} topic={question.topic}"
            )
            print(f"  {_truncate_question(question.question_text)}")
        return

    if args.command == "alpha-demo-setup":
        result = alpha_demo_setup(
            db_path=args.db_path,
            session_name=args.session_name,
            topic=args.topic,
            question=args.question,
        )
        session = result["session"]
        panel_question = result["panel_question"]
        assessment = result["assessment"]
        combined = result["combined"]
        print("Alpha demo is ready.")
        print(f"Session: {session.id} ({session.name})")
        print(f"Seeded active decision: {result['active_decision'].id}")
        print(f"Seeded open candidate: {result['candidate'].id}")
        print(f"Panel question id: {panel_question.id}")
        print(f"Assessment: {alignment_label(assessment.alignment)}")
        print(f"Recommendation: {combined}")
        print("Suggested follow-up commands:")
        print(
            f"- python src/main.py --db-path {args.db_path} "
            f"show-panel-question --question-id {panel_question.id}"
        )
        print(f"- python src/main.py --db-path {args.db_path} list-panel-questions --topic {args.topic}")
        print(f"- python src/main.py --db-path {args.db_path} tui")
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
    print("Onboarding tip:")
    print(f"- Quick demo: python src/main.py --db-path {args.db_path} alpha-demo-setup")
    print(f"- Open dashboard: python src/main.py --db-path {args.db_path} tui")


if __name__ == "__main__":
    main()
