from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    status: Literal["active", "completed", "failed"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    description: str
    priority: int = 0
    owner_agent: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str
    agent_name: str
    kind: Literal["result", "error", "system"] = "result"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    scope: Literal["session", "project", "user"] = "session"
    kind: Literal["fact", "decision", "preference", "summary", "open_question"] = "fact"
    source_agent: str | None = None
    task_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    event_type: Literal[
        "session_created",
        "session_status_changed",
        "task_created",
        "task_routed",
        "task_completed",
        "task_failed",
        "memory_created",
        "decision_created",
        "decision_candidate_created",
        "decision_candidate_confirmed",
        "decision_candidate_dismissed",
        "decision_link_created",
        "decision_suggestion_created",
        "decision_suggestion_accepted",
        "decision_suggestion_dismissed",
    ]
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    title: str
    topic: str
    decision_text: str
    rationale: str | None = None
    background: str | None = None
    assumptions: str | None = None
    risks: str | None = None
    alternatives_considered: str | None = None
    consequences: str | None = None
    follow_up_notes: str | None = None
    status: Literal["active", "superseded", "revoked"] = "active"
    owner: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    effective_from: datetime | None = None
    review_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class DecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    title: str
    topic: str
    candidate_text: str
    rationale: str | None = None
    status: Literal["proposed", "confirmed", "dismissed"] = "proposed"
    owner: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)


class DecisionLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    from_decision_id: str
    to_decision_id: str
    relation_type: Literal["supersedes", "clarifies", "supplements"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_decision_id: str
    target_decision_id: str
    suggestion_type: Literal["related_decision", "possible_supersedes", "possible_conflict"]
    reason: str
    status: Literal["open", "accepted", "dismissed"] = "open"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdvisorRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["strateg", "analyst", "operator", "governance"]
    purpose: str
    output_style: str
    active: bool = True
    is_default: bool = True


class ReasoningItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    decision_id: str | None = None
    question_id: str | None = None
    kind: Literal["risk", "objection", "assumption", "rationale", "open_question"]
    content: str
    source_type: Literal["panel", "system", "operator", "agent", "manual"] = "system"
    memory_level: Literal["transient", "private_context", "formal_decision"] = "private_context"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutiveQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    question_text: str
    topic: str
    session_id: str | None = None
    status: Literal["open", "answered", "closed"] = "open"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PanelQuestion(ExecutiveQuestion):
    """Backward compatible alias while moving to ExecutiveQuestion as domain model."""

    @property
    def question(self) -> str:
        return self.question_text


class PanelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    question_id: str
    agent_name: Literal["strateg", "analyst", "operator", "governance"]
    response_text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionAlignmentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alignment: Literal[
        "aligned",
        "clarification_needed",
        "potential_deviation",
        "likely_new_decision_required",
    ]
    reason: str
    active_decision_ids: list[str] = Field(default_factory=list)
    challenge_points: list[str] = Field(default_factory=list)


class PanelOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_mode: Literal[
        "execution_under_active_decision",
        "clarification_of_active_decision",
        "potential_deviation",
        "likely_new_decision_required",
    ]
    likely_requires_new_decision: Literal["yes", "no", "probably"]
    can_execute_now: bool
    formal_next_step: str


class ExecutiveQuestionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    question_id: str
    assessment_alignment: Literal[
        "aligned",
        "clarification_needed",
        "potential_deviation",
        "likely_new_decision_required",
    ]
    assessment_reason: str
    challenge_points: list[str] = Field(default_factory=list)
    combined_recommendation: str
    suggested_next_step: str
    likely_requires_new_decision: Literal["yes", "no", "probably"]
    question_interpretation: str | None = None
    relevant_context: dict[str, object] = Field(default_factory=dict)
    per_role_analysis: dict[str, str] = Field(default_factory=dict)
    tensions: list[str] = Field(default_factory=list)
    decision_status_assessment: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
