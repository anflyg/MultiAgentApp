from multi_agent_app.memory_core import SocratesMemory
from multi_agent_app.storage import Storage


def test_storage_workspace_active_state_roundtrip():
    storage = Storage(db_path=":memory:")
    try:
        default_workspace = storage.get_active_workspace()
        assert default_workspace.name == "Default"

        workspace = storage.create_workspace(name="Strategy", description="Strategy scope")
        storage.set_active_workspace(workspace.id)
        active = storage.get_active_workspace()
        assert active.id == workspace.id
        assert active.name == "Strategy"
    finally:
        storage.close()


def test_storage_save_get_and_list_socrates_memories():
    storage = Storage(db_path=":memory:")
    try:
        workspace_a = storage.create_workspace(name="Workspace A", description="")
        workspace_b = storage.create_workspace(name="Workspace B", description="")

        memory_a = SocratesMemory(
            workspace_id=workspace_a.id,
            title="Nordic expansion memory",
            summary="Keep expansion staged in Norway.",
            assumptions=["Margin must stay above threshold."],
            risks=["Fast expansion may increase burn."],
            triggers=["margin below threshold"],
        )
        memory_b = SocratesMemory(
            workspace_id=workspace_b.id,
            title="Liquidity runway memory",
            summary="Maintain 12-month runway.",
        )
        storage.save_socrates_memory(memory_a)
        storage.save_socrates_memory(memory_b)

        loaded = storage.get_socrates_memory(memory_a.id)
        assert loaded is not None
        assert loaded.id == memory_a.id
        assert loaded.workspace_id == workspace_a.id
        assert loaded.assumptions == ["Margin must stay above threshold."]

        scoped = storage.list_socrates_memories(workspace_id=workspace_a.id, limit=10)
        assert [item.id for item in scoped] == [memory_a.id]

        unscoped = storage.list_socrates_memories(limit=10)
        ids = {item.id for item in unscoped}
        assert memory_a.id in ids
        assert memory_b.id in ids
    finally:
        storage.close()
