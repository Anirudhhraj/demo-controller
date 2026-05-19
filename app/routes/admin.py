"""Admin / override endpoints. All require the X-Admin-Token header."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_admin
from app.compute import get_vm_status
from app.config import get_demos
from app.reaper import run as run_reaper
from app.state import get as get_state, update as update_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/status")
def status_dump() -> dict:
    out: dict = {}
    for demo_id in get_demos():
        try:
            vm_state = get_vm_status(demo_id).state
        except Exception:
            logger.exception("admin status: read failed for %s", demo_id)
            vm_state = "ERROR"
        s = get_state(demo_id)
        out[demo_id] = {
            "vm_state": vm_state,
            "started_by": s.started_by,
            "session_id": s.session_id,
            "session_last_seen": s.session_last_seen,
            "locked_until": s.locked_until,
            "last_action": s.last_action,
        }
    return out


@router.post("/demos/{demo_id}/lock")
def lock(demo_id: str, hours: int = Query(default=4, ge=1, le=72)) -> dict:
    if demo_id not in get_demos():
        raise HTTPException(404, f"unknown demo: {demo_id}")
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    update_state(demo_id, locked_until=until.isoformat())
    return {"locked_until": until.isoformat()}


@router.post("/demos/{demo_id}/unlock")
def unlock(demo_id: str) -> dict:
    if demo_id not in get_demos():
        raise HTTPException(404, f"unknown demo: {demo_id}")
    update_state(demo_id, locked_until=None)
    return {"unlocked": True}


@router.post("/demos/{demo_id}/take")
def take(demo_id: str) -> dict:
    """Mark VM as owner-managed. Reaper will never touch it."""
    if demo_id not in get_demos():
        raise HTTPException(404, f"unknown demo: {demo_id}")
    update_state(demo_id, started_by="manual", session_id=None, session_last_seen=None)
    return {"started_by": "manual"}


@router.post("/demos/{demo_id}/release-ownership")
def release_ownership(demo_id: str) -> dict:
    """Reset ownership. Next portfolio visitor can manage lifecycle again."""
    if demo_id not in get_demos():
        raise HTTPException(404, f"unknown demo: {demo_id}")
    update_state(demo_id, started_by=None, session_id=None, session_last_seen=None)
    return {"started_by": None}


@router.post("/reaper/run")
def trigger_reaper() -> dict:
    """Manual reaper trigger. Cloud Scheduler will hit this on a 1-min cron in production."""
    return run_reaper()