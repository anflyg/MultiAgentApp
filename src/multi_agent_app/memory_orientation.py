from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .memory_retrieval import retrieve_relevant_memory_matches
from .storage import Storage

_TOKEN_RE = re.compile(r"[0-9a-zA-ZåäöÅÄÖ]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "att",
    "be",
    "bör",
    "det",
    "for",
    "hur",
    "i",
    "in",
    "is",
    "med",
    "men",
    "next",
    "och",
    "of",
    "on",
    "or",
    "ska",
    "som",
    "the",
    "this",
    "to",
    "vi",
    "vad",
}


class OrientationTopMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str
    relevance_score: float
    match_basis: list[str] = Field(default_factory=list)


class MemoryOrientationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    workspace: str
    top_matches: list[OrientationTopMatch] = Field(default_factory=list)
    memory_belongs: Literal["likely_related", "weakly_related", "no_clear_match"]
    novelty_assessment: Literal["existing", "partly_new", "new"]
    reasoning: str


def orient_question_to_memory(
    storage: Storage,
    *,
    question: str,
    workspace_id: str | None = None,
    limit: int = 3,
) -> MemoryOrientationResult:
    normalized_question = " ".join(question.strip().split())
    if not normalized_question:
        raise ValueError("Question cannot be empty")

    workspace = workspace_id or storage.get_active_workspace().id
    matches = retrieve_relevant_memory_matches(
        storage,
        workspace_id=workspace,
        question=normalized_question,
        limit=limit,
    )

    if not matches:
        return MemoryOrientationResult(
            question=normalized_question,
            workspace=workspace,
            top_matches=[],
            memory_belongs="no_clear_match",
            novelty_assessment="new",
            reasoning="No relevant memory match found in workspace scope.",
        )

    query_tokens = _tokenize(normalized_question)
    top = matches[0]
    coverage = (
        len(set(top.match_basis)) / max(len(query_tokens), 1)
        if query_tokens
        else 0.0
    )
    top_score = top.relevance_score

    memory_belongs: Literal["likely_related", "weakly_related", "no_clear_match"]
    novelty: Literal["existing", "partly_new", "new"]
    if top_score >= 0.75 and coverage >= 0.5:
        memory_belongs = "likely_related"
        novelty = "existing"
    elif top_score >= 0.25 and coverage >= 0.2:
        memory_belongs = "weakly_related" if top_score < 0.45 else "likely_related"
        novelty = "partly_new"
    else:
        memory_belongs = "no_clear_match"
        novelty = "new"

    top_matches = [
        OrientationTopMatch(
            id=match.memory.id,
            title=match.memory.title,
            summary=match.memory.summary,
            relevance_score=round(match.relevance_score, 3),
            match_basis=match.match_basis,
        )
        for match in matches
    ]
    reasoning = (
        f"Top match score={top_score:.2f}, token_overlap={coverage:.2f}, "
        f"match_basis={','.join(top.match_basis[:4]) or '-'}."
    )
    return MemoryOrientationResult(
        question=normalized_question,
        workspace=workspace,
        top_matches=top_matches,
        memory_belongs=memory_belongs,
        novelty_assessment=novelty,
        reasoning=reasoning,
    )


def orient_question_to_memory_by_db(
    db_path: str,
    *,
    question: str,
    workspace_id: str | None = None,
    limit: int = 3,
) -> MemoryOrientationResult:
    storage = Storage(db_path=db_path)
    try:
        return orient_question_to_memory(
            storage,
            question=question,
            workspace_id=workspace_id,
            limit=limit,
        )
    finally:
        storage.close()


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    return {
        token
        for token in _TOKEN_RE.findall(lowered)
        if len(token) >= 2 and token not in _STOPWORDS
    }
