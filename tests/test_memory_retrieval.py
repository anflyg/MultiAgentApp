from multi_agent_app.memory_core import SocratesMemory
from multi_agent_app.memory_retrieval import (
    get_workspace_memory,
    list_workspace_memories,
    retrieve_relevant_memories,
)
from multi_agent_app.storage import Storage


def test_memory_retrieval_list_and_get_respects_workspace_scope():
    storage = Storage(db_path=":memory:")
    try:
        ws_a = storage.create_workspace(name="Strategi Scope", description="")
        ws_b = storage.create_workspace(name="Ekonomi Scope", description="")

        mem_a = SocratesMemory(
            workspace_id=ws_a.id,
            title="Strategy memory",
            summary="Expansion gate for market X.",
        )
        mem_b = SocratesMemory(
            workspace_id=ws_b.id,
            title="Finance memory",
            summary="Liquidity safety policy.",
        )
        storage.save_socrates_memory(mem_a)
        storage.save_socrates_memory(mem_b)

        listed = list_workspace_memories(storage, workspace_id=ws_a.id, limit=10)
        assert len(listed) == 1
        assert listed[0].id == mem_a.id

        loaded_in_scope = get_workspace_memory(storage, workspace_id=ws_a.id, memory_id=mem_a.id)
        loaded_other_scope = get_workspace_memory(storage, workspace_id=ws_a.id, memory_id=mem_b.id)
        assert loaded_in_scope is not None
        assert loaded_in_scope.id == mem_a.id
        assert loaded_other_scope is None
    finally:
        storage.close()


def test_memory_retrieval_returns_relevant_memories_by_simple_text_match():
    storage = Storage(db_path=":memory:")
    try:
        ws = storage.create_workspace(name="Strategi", description="")
        high_match = SocratesMemory(
            workspace_id=ws.id,
            title="Expansion margin guardrail",
            summary="Pause expansion when gross margin is under target.",
            decision_text="Keep expansion paused until margin improves.",
            assumptions=["Margin can recover during Q3."],
            risks=["Aggressive expansion hurts margin further."],
            triggers=["margin below target for two months"],
        )
        low_match = SocratesMemory(
            workspace_id=ws.id,
            title="Leadership hiring rhythm",
            summary="Review executive hiring every quarter.",
        )
        storage.save_socrates_memory(high_match)
        storage.save_socrates_memory(low_match)

        hits = retrieve_relevant_memories(
            storage,
            workspace_id=ws.id,
            question="Ska vi pausa expansion när marginalen är för låg?",
            limit=5,
        )
        assert hits
        assert hits[0].id == high_match.id
        assert all(hit.workspace_id == ws.id for hit in hits)
    finally:
        storage.close()


def test_memory_retrieval_keeps_workspace_scope_before_relevance():
    storage = Storage(db_path=":memory:")
    try:
        ws_a = storage.create_workspace(name="Strategi A", description="")
        ws_b = storage.create_workspace(name="Strategi B", description="")
        scoped_memory = SocratesMemory(
            workspace_id=ws_a.id,
            title="Expansion pause policy",
            summary="Pause expansion in market X under low margin.",
        )
        stronger_other_workspace = SocratesMemory(
            workspace_id=ws_b.id,
            title="Expansion pause policy with full details",
            summary="Pause expansion in market X under low margin and high churn.",
            decision_text="Immediate pause if margin and retention targets fail.",
        )
        storage.save_socrates_memory(scoped_memory)
        storage.save_socrates_memory(stronger_other_workspace)

        hits = retrieve_relevant_memories(
            storage,
            workspace_id=ws_a.id,
            question="Should we pause expansion in market X now?",
            limit=5,
        )
        assert len(hits) == 1
        assert hits[0].id == scoped_memory.id
    finally:
        storage.close()
