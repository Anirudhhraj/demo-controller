"""Shared fixtures.

Critical: env vars are set at MODULE LOAD time, before any `from app...` import,
because `app/config.py` validates env at import. The per-test fixture then
isolates the state file and clears the config cache so each test sees fresh state.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ---- Module-level env setup (runs once at collection time) ----
_TEST_DIR = Path(tempfile.mkdtemp(prefix="democtl_test_"))
_DEMOS_YAML = _TEST_DIR / "demos.yaml"
_DEMOS_YAML.write_text(
    """
demos:
  cs5:
    name: "CS5 Test"
    instance: cs5-prod-vm-v2
    zone: us-east1-d
    healthUrl: http://34.26.144.212:8501/_stcore/health
    appUrl: http://34.26.144.212:8501/comparative/
    idleMinutes: 10
  vicinity:
    name: "Vicinity Test"
    instance: vicinity-prod-vm
    zone: us-east1-c
    healthUrl: http://34.74.93.251/
    appUrl: http://34.74.93.251/
    idleMinutes: 10
""",
    encoding="utf-8",
)

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("DEMOS_CONFIG_PATH", str(_DEMOS_YAML))
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-1234567890")
os.environ.setdefault("ALLOWED_ORIGINS", "")


# ---- Per-test fixtures ----
@pytest.fixture(autouse=True)
def _fresh_state(tmp_path, monkeypatch):
    """Each test gets its own state file, file backend forced, fresh caches."""
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("STATE_FILE_PATH", str(state_file))
    monkeypatch.delenv("STATE_BUCKET", raising=False)  # force file backend in tests

    from app.config import get_app_config, get_demos
    from app.state import _reset_backend_for_tests
    get_app_config.cache_clear()
    get_demos.cache_clear()
    _reset_backend_for_tests()
    yield state_file
    get_app_config.cache_clear()
    get_demos.cache_clear()
    _reset_backend_for_tests()


@pytest.fixture
def admin_token() -> str:
    return os.environ["ADMIN_TOKEN"]


@pytest.fixture
def client():
    """FastAPI TestClient. Lazy import keeps env-var setup ordering safe."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    return TestClient(create_app())


@pytest.fixture
def mock_compute(mocker):
    """Replace GCP calls with an in-memory state dict.

    Note: we patch in every module that did `from app.compute import X`,
    because Python's import-by-name creates separate references.
    """
    from app.compute import VmStatus

    state = {"cs5": "TERMINATED", "vicinity": "TERMINATED"}
    ips = {"cs5": "34.26.144.212", "vicinity": "34.74.93.251"}

    def fake_status(demo_id: str) -> VmStatus:
        return VmStatus(state=state[demo_id], external_ip=ips[demo_id])

    def fake_start(demo_id: str) -> None:
        state[demo_id] = "RUNNING"

    def fake_stop(demo_id: str) -> None:
        state[demo_id] = "TERMINATED"

    start_mock = mocker.patch("app.routes.demos.start_vm", side_effect=fake_start)
    demos_stop_mock = mocker.patch("app.routes.demos.stop_vm", side_effect=fake_stop)
    reaper_stop_mock = mocker.patch("app.reaper.stop_vm", side_effect=fake_stop)
    mocker.patch("app.routes.demos.get_vm_status", side_effect=fake_status)
    mocker.patch("app.reaper.get_vm_status", side_effect=fake_status)
    mocker.patch("app.routes.admin.get_vm_status", side_effect=fake_status)
    mocker.patch("app.routes.demos._check_app_healthy", return_value=True)

    class Handle:
        def set_state(self, demo_id: str, value: str) -> None:
            state[demo_id] = value
        def get_state(self, demo_id: str) -> str:
            return state[demo_id]
        @property
        def starts(self):
            return start_mock.call_args_list
        @property
        def stops(self):
            return demos_stop_mock.call_args_list + reaper_stop_mock.call_args_list

    return Handle()