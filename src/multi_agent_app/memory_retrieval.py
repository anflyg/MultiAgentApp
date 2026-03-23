from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .memory_core import SocratesMemory
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


@dataclass(frozen=True)
class MemoryMatch:
    memory: SocratesMemory
    raw_score: int
    relevance_score: float
    match_basis: list[str]


def list_workspace_memories(
    storage: Storage,
    *,
    workspace_id: str,
    limit: int = 50,
) -> list[SocratesMemory]:
    return storage.list_socrates_memories(workspace_id=workspace_id, limit=limit)


def get_workspace_memory(
    storage: Storage,
    *,
    workspace_id: str,
    memory_id: str,
) -> SocratesMemory | None:
    memory = storage.get_socrates_memory(memory_id)
    if memory is None:
        return None
    if memory.workspace_id != workspace_id:
        return None
    return memory


def retrieve_relevant_memories(
    storage: Storage,
    *,
    workspace_id: str,
    question: str,
    limit: int = 5,
    scan_limit: int = 200,
) -> list[SocratesMemory]:
    matches = retrieve_relevant_memory_matches(
        storage,
        workspace_id=workspace_id,
        question=question,
        limit=limit,
        scan_limit=scan_limit,
    )
    return [match.memory for match in matches]


def retrieve_relevant_memory_matches(
    storage: Storage,
    *,
    workspace_id: str,
    question: str,
    limit: int = 5,
    scan_limit: int = 200,
) -> list[MemoryMatch]:
    query_tokens = _tokenize(question)
    if not query_tokens:
        return []

    memories = storage.list_socrates_memories(workspace_id=workspace_id, limit=scan_limit)
    scored: list[MemoryMatch] = []
    for memory in memories:
        score = _score_memory(memory, query_tokens)
        if score <= 0:
            continue
        basis = sorted(query_tokens & _memory_tokens(memory))
        scored.append(
            MemoryMatch(
                memory=memory,
                raw_score=score,
                relevance_score=_normalize_score(score, query_tokens_count=len(query_tokens)),
                match_basis=basis[:8],
            )
        )

    scored.sort(
        key=lambda item: (
            item.raw_score,
            item.memory.updated_at,
            item.memory.created_at,
        ),
        reverse=True,
    )
    return scored[:limit]


def _score_memory(memory: SocratesMemory, query_tokens: set[str]) -> int:
    score = 0
    score += 3 * len(query_tokens & _tokenize(memory.title))
    score += 2 * len(query_tokens & _tokenize(memory.summary))
    score += 2 * len(query_tokens & _tokenize(memory.decision_text or ""))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.assumptions))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.risks))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.triggers))
    return score


def _normalize_score(score: int, *, query_tokens_count: int) -> float:
    denominator = max(query_tokens_count * 3, 1)
    return min(score / denominator, 1.0)


def _memory_tokens(memory: SocratesMemory) -> set[str]:
    combined: set[str] = set()
    combined |= _tokenize(memory.title)
    combined |= _tokenize(memory.summary)
    combined |= _tokenize(memory.decision_text or "")
    combined |= _tokenize_from_items(memory.assumptions)
    combined |= _tokenize_from_items(memory.risks)
    combined |= _tokenize_from_items(memory.triggers)
    return combined


def _tokenize_from_items(items: Iterable[str]) -> set[str]:
    joined = " ".join(items)
    return _tokenize(joined)


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    return {
        token
        for token in _TOKEN_RE.findall(lowered)
        if len(token) >= 2 and token not in _STOPWORDS
    }
