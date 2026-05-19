"""Live GCP tests. Opt-in via RUN_INTEGRATION=1.

These hit your real cs5-prod-vm-v2 and vicinity-prod-vm VMs.
They do NOT start/stop anything — read-only.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 to run live GCP tests",
)


def test_cs5_status_is_readable(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "pe-org-air")
    from app.config import get_app_config
    get_app_config.cache_clear()

    from app.compute import get_vm_status
    vm = get_vm_status("cs5")
    assert vm.state in ("RUNNING", "TERMINATED", "STOPPING", "PROVISIONING", "STAGING")
    if vm.state == "RUNNING":
        assert vm.external_ip == "34.26.144.212"


def test_vicinity_status_is_readable(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "pe-org-air")
    from app.config import get_app_config
    get_app_config.cache_clear()

    from app.compute import get_vm_status
    vm = get_vm_status("vicinity")
    assert vm.state in ("RUNNING", "TERMINATED", "STOPPING", "PROVISIONING", "STAGING")
    if vm.state == "RUNNING":
        assert vm.external_ip == "34.74.93.251"