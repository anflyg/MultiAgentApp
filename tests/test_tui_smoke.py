import pytest


def test_tui_smoke_import_and_init():
    pytest.importorskip("textual")
    from multi_agent_app.tui import MultiAgentTUI

    app = MultiAgentTUI(db_path=":memory:")
    assert app.db_path == ":memory:"
