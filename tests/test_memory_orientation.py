from multi_agent_app.memory_core import SocratesMemory
from multi_agent_app.memory_orientation import orient_question_to_memory
from multi_agent_app.storage import Storage


def test_memory_orientation_existing_when_strong_match():
    storage = Storage(db_path=":memory:")
    try:
        ws = storage.create_workspace(name="Strategi Existing", description="")
        storage.save_socrates_memory(
            SocratesMemory(
                workspace_id=ws.id,
                title="Nordisk expansion Norge 2026",
                summary="Stegvis expansion i Norge med marginalvakt.",
                decision_text="Fortsätt expansion i Norge när bruttomarginalen är stabil.",
                assumptions=["Norge prioriteras i nordisk plan."],
                risks=["Svag marginal vid för snabb expansion."],
                triggers=["bruttomarginal under målnivå"],
            )
        )
        result = orient_question_to_memory(
            storage,
            workspace_id=ws.id,
            question="Hur bör vi tänka kring expansion i Norge med marginalvakt 2026?",
        )
        assert result.top_matches
        assert result.memory_belongs == "likely_related"
        assert result.novelty_assessment == "existing"
    finally:
        storage.close()


def test_memory_orientation_partly_new_when_partial_overlap():
    storage = Storage(db_path=":memory:")
    try:
        ws = storage.create_workspace(name="Strategi Partial", description="")
        storage.save_socrates_memory(
            SocratesMemory(
                workspace_id=ws.id,
                title="Nordisk expansion",
                summary="Stegvis expansion i Norden med fokus på Norge.",
                decision_text="Expansion sker i etapper.",
            )
        )
        result = orient_question_to_memory(
            storage,
            workspace_id=ws.id,
            question="Hur bör vi utvärdera expansion i Norge tillsammans med ny partnerkanal?",
        )
        assert result.top_matches
        assert result.novelty_assessment == "partly_new"
        assert result.memory_belongs in {"likely_related", "weakly_related"}
    finally:
        storage.close()


def test_memory_orientation_new_when_no_clear_match():
    storage = Storage(db_path=":memory:")
    try:
        ws = storage.create_workspace(name="Strategi New", description="")
        storage.save_socrates_memory(
            SocratesMemory(
                workspace_id=ws.id,
                title="Nordisk expansion",
                summary="Fokus på marknadsexpansion i Norden.",
            )
        )
        result = orient_question_to_memory(
            storage,
            workspace_id=ws.id,
            question="Hur ska vi lägga upp ledningsersättning för CFO och HR nästa år?",
        )
        assert result.novelty_assessment == "new"
        assert result.memory_belongs == "no_clear_match"
    finally:
        storage.close()
