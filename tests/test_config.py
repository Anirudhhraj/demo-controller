"""Config loading and demo registry lookup."""
import pytest


def test_app_config_loads():
    from app.config import get_app_config
    cfg = get_app_config()
    assert cfg.gcp_project_id == "test-project"
    assert cfg.admin_token.startswith("test-admin-token")


def test_demos_load():
    from app.config import get_demos
    demos = get_demos()
    assert set(demos.keys()) == {"cs5", "vicinity"}
    assert demos["cs5"].instance == "cs5-prod-vm-v2"
    assert demos["cs5"].zone == "us-east1-d"
    assert demos["vicinity"].instance == "vicinity-prod-vm"


def test_get_demo_known():
    from app.config import get_demo
    assert get_demo("cs5").id == "cs5"


def test_get_demo_unknown_raises():
    from app.config import get_demo
    with pytest.raises(KeyError):
        get_demo("nonexistent")


def test_missing_required_env_fails(monkeypatch):
    from app.config import get_app_config
    get_app_config.cache_clear()
    monkeypatch.delenv("GCP_PROJECT_ID")
    with pytest.raises(RuntimeError, match="Missing required env var"):
        get_app_config()