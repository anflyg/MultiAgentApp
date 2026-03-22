from __future__ import annotations

import re
from typing import Iterable

from .memory_core import SocratesMemory
from .storage import Storage

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


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
    query_tokens = _tokenize(question)
    if not query_tokens:
        return []

    memories = storage.list_socrates_memories(workspace_id=workspace_id, limit=scan_limit)
    scored: list[tuple[int, SocratesMemory]] = []
    for memory in memories:
        score = _score_memory(memory, query_tokens)
        if score > 0:
            scored.append((score, memory))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].updated_at,
            item[1].created_at,
        ),
        reverse=True,
    )
    return [memory for _, memory in scored[:limit]]


def _score_memory(memory: SocratesMemory, query_tokens: set[str]) -> int:
    score = 0
    score += 3 * len(query_tokens & _tokenize(memory.title))
    score += 2 * len(query_tokens & _tokenize(memory.summary))
    score += 2 * len(query_tokens & _tokenize(memory.decision_text or ""))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.assumptions))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.risks))
    score += 1 * len(query_tokens & _tokenize_from_items(memory.triggers))
    return score


def _tokenize_from_items(items: Iterable[str]) -> set[str]:
    joined = " ".join(items)
    return _tokenize(joined)


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    return {token for token in _TOKEN_RE.findall(lowered) if len(token) >= 2}
