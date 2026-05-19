"""State store CRUD + corruption recovery."""
import pytest


def test_initial_state_is_empty():
    from app.state import get
    s = get("cs5")
    assert s.started_by is None
    assert s.session_id is None
    assert s.session_last_seen is None
    assert s.locked_until is None


def test_update_persists():
    from app.state import get, update
    update("cs5", started_by="portfolio", session_id="abc")
    s = get("cs5")
    assert s.started_by == "portfolio"
    assert s.session_id == "abc"
    assert s.last_action is not None  # auto-stamped


def test_update_unknown_field_rejected():
    from app.state import update
    with pytest.raises(ValueError, match="unknown state fields"):
        update("cs5", bogus_field="nope")


def test_list_all_returns_all_demos():
    from app.state import update, list_all
    update("cs5", started_by="portfolio")
    update("vicinity", started_by="manual")
    all_states = list_all()
    assert all_states["cs5"].started_by == "portfolio"
    assert all_states["vicinity"].started_by == "manual"


def test_clears_field_with_none():
    from app.state import get, update
    update("cs5", started_by="portfolio")
    update("cs5", started_by=None)
    assert get("cs5").started_by is None


def test_corrupted_state_file_recovers(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setenv("STATE_FILE_PATH", str(bad))
    from app.config import get_app_config
    get_app_config.cache_clear()

    from app.state import get
    s = get("cs5")  # should not raise
    assert s.started_by is None