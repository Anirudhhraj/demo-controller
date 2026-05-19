"""Idle-shutdown decision logic. Runs on demand or on a schedule.

Rule: stop a VM iff
  - started_by == "portfolio"   (we own its lifecycle)
  - AND session_last_seen is older than the demo's idleMinutes
  - AND locked_until is in the past or unset
  - AND VM is currently RUNNING (avoid no-op stops)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.compute import get_vm_status, stop_vm
from app.config import get_demos
from app.state import get as get_state, update as update_state

logger = logging.getLogger(__name__)


def _is_stale(last_seen_iso: Optional[str], idle_minutes: int) -> bool:
    if not last_seen_iso:
        return True
    try:
        last_seen = datetime.fromisoformat(last_seen_iso)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last_seen > timedelta(minutes=idle_minutes)


def _is_locked(locked_until_iso: Optional[str]) -> bool:
    if not locked_until_iso:
        return False
    try:
        return datetime.now(timezone.utc) < datetime.fromisoformat(locked_until_iso)
    except ValueError:
        return False


def run() -> dict:
    summary: dict = {"checked": 0, "stopped": [], "skipped": []}

    for demo_id, demo in get_demos().items():
        summary["checked"] += 1
        state = get_state(demo_id)

        if state.started_by != "portfolio":
            summary["skipped"].append({"demo": demo_id, "reason": f"started_by={state.started_by}"})
            continue
        if _is_locked(state.locked_until):
            summary["skipped"].append({"demo": demo_id, "reason": "locked"})
            continue
        if not _is_stale(state.session_last_seen, demo.idleMinutes):
            summary["skipped"].append({"demo": demo_id, "reason": "active"})
            continue

        try:
            vm = get_vm_status(demo_id)
        except Exception:
            logger.exception("reaper: status read failed for %s", demo_id)
            summary["skipped"].append({"demo": demo_id, "reason": "status_error"})
            continue

        if vm.state == "TERMINATED":
            summary["skipped"].append({"demo": demo_id, "reason": "already_stopped"})
            continue

        try:
            stop_vm(demo_id)
            update_state(demo_id, started_by=None, session_id=None, session_last_seen=None)
            summary["stopped"].append(demo_id)
            logger.info("reaper: stopped %s (idle)", demo_id)
        except Exception:
            logger.exception("reaper: stop failed for %s", demo_id)
            summary["skipped"].append({"demo": demo_id, "reason": "stop_error"})

    return summary