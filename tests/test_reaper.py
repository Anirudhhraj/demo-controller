"""Reaper rule evaluation. Mocks GCP so it's pure logic testing."""
from datetime import datetime, timedelta, timezone


def _iso_minutes_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


def _iso_hours_from_now(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=n)).isoformat()


def test_skips_manual_owned(mock_compute):
    from app.reaper import run
    from app.state import update
    mock_compute.set_state("cs5", "RUNNING")
    update("cs5", started_by="manual", session_last_seen=_iso_minutes_ago(30))
    result = run()
    assert "cs5" not in result["stopped"]
    assert len(mock_compute.stops) == 0


def test_skips_unowned(mock_compute):
    from app.reaper import run
    mock_compute.set_state("cs5", "RUNNING")
    result = run()
    assert "cs5" not in result["stopped"]
    assert len(mock_compute.stops) == 0


def test_skips_locked(mock_compute):
    from app.reaper import run
    from app.state import update
    mock_compute.set_state("cs5", "RUNNING")
    update(
        "cs5",
        started_by="portfolio",
        session_last_seen=_iso_minutes_ago(30),
        locked_until=_iso_hours_from_now(1),
    )
    result = run()
    assert "cs5" not in result["stopped"]


def test_skips_active(mock_compute):
    from app.reaper import run
    from app.state import update
    mock_compute.set_state("cs5", "RUNNING")
    update("cs5", started_by="portfolio", session_last_seen=_iso_minutes_ago(1))
    result = run()
    assert "cs5" not in result["stopped"]


def test_skips_already_terminated(mock_compute):
    from app.reaper import run
    from app.state import update
    mock_compute.set_state("cs5", "TERMINATED")
    update("cs5", started_by="portfolio", session_last_seen=_iso_minutes_ago(30))
    result = run()
    assert "cs5" not in result["stopped"]
    assert len(mock_compute.stops) == 0


def test_stops_idle_portfolio_owned(mock_compute):
    from app.reaper import run
    from app.state import get, update
    mock_compute.set_state("cs5", "RUNNING")
    update("cs5", started_by="portfolio", session_last_seen=_iso_minutes_ago(30))
    result = run()
    assert "cs5" in result["stopped"]
    assert len(mock_compute.stops) == 1
    # State should be cleared after stop
    assert get("cs5").started_by is None
    assert get("cs5").session_id is None


def test_summary_shape(mock_compute):
    from app.reaper import run
    result = run()
    assert result["checked"] == 2  # cs5 + vicinity
    assert isinstance(result["stopped"], list)
    assert isinstance(result["skipped"], list)