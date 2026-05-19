"""Public lifecycle endpoints called by the portfolio."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.compute import get_vm_status, start_vm, stop_vm
from app.config import get_demo
from app.state import get as get_state, now_iso, update as update_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/demos", tags=["demos"])


class StartResponse(BaseModel):
    session_id: str
    already_running: bool


class StatusResponse(BaseModel):
    state: str                 # stopped | starting | booting | ready | error
    app_url: str
    started_by: Optional[str]
    locked: bool


class SessionBody(BaseModel):
    session_id: str


def _check_app_healthy(health_url: str) -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(health_url)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _is_locked(locked_until_iso: Optional[str]) -> bool:
    if not locked_until_iso:
        return False
    try:
        return datetime.now(timezone.utc) < datetime.fromisoformat(locked_until_iso)
    except ValueError:
        return False


@router.post("/{demo_id}/start", response_model=StartResponse)
def start(demo_id: str) -> StartResponse:
    try:
        get_demo(demo_id)
    except KeyError:
        raise HTTPException(404, f"unknown demo: {demo_id}")

    try:
        vm = get_vm_status(demo_id)
    except Exception:
        logger.exception("start: status read failed for %s", demo_id)
        raise HTTPException(502, "failed to read VM state")

    session_id = str(uuid.uuid4())

    if vm.state == "RUNNING":
        current = get_state(demo_id)
        if current.started_by is None:
            update_state(demo_id, started_by="manual")
        return StartResponse(session_id=session_id, already_running=True)

    if vm.state in ("STOPPING", "TERMINATED"):
        try:
            start_vm(demo_id)
        except Exception:
            logger.exception("start: start_vm failed for %s", demo_id)
            raise HTTPException(502, "failed to start VM")
        update_state(
            demo_id,
            started_by="portfolio",
            session_id=session_id,
            session_last_seen=now_iso(),
        )
        return StartResponse(session_id=session_id, already_running=False)

    # Transitional states (PROVISIONING/STAGING): just register the session
    update_state(demo_id, session_id=session_id, session_last_seen=now_iso())
    return StartResponse(session_id=session_id, already_running=False)


@router.get("/{demo_id}/status", response_model=StatusResponse)
def status(demo_id: str) -> StatusResponse:
    try:
        demo = get_demo(demo_id)
    except KeyError:
        raise HTTPException(404, f"unknown demo: {demo_id}")

    try:
        vm = get_vm_status(demo_id)
    except Exception:
        logger.exception("status: read failed for %s", demo_id)
        return StatusResponse(state="error", app_url=demo.appUrl, started_by=None, locked=False)

    s = get_state(demo_id)
    locked = _is_locked(s.locked_until)

    if vm.state == "TERMINATED":
        return StatusResponse(state="stopped", app_url=demo.appUrl, started_by=s.started_by, locked=locked)
    if vm.state == "RUNNING":
        ready = _check_app_healthy(demo.healthUrl)
        return StatusResponse(
            state="ready" if ready else "booting",
            app_url=demo.appUrl,
            started_by=s.started_by,
            locked=locked,
        )
    if vm.state == "STOPPING":
            return StatusResponse(state="stopping", app_url=demo.appUrl, started_by=s.started_by, locked=locked)
    # PROVISIONING, STAGING
    return StatusResponse(state="starting", app_url=demo.appUrl, started_by=s.started_by, locked=locked)

@router.post("/{demo_id}/heartbeat")
def heartbeat(demo_id: str, body: SessionBody) -> dict:
    try:
        get_demo(demo_id)
    except KeyError:
        raise HTTPException(404, f"unknown demo: {demo_id}")
    current = get_state(demo_id)
    if current.session_id != body.session_id:
        return {"accepted": False, "reason": "session mismatch"}
    update_state(demo_id, session_last_seen=now_iso())
    return {"accepted": True}


@router.post("/{demo_id}/release")
def release(demo_id: str, body: SessionBody) -> dict:
    """Iframe closed: stop the VM early, but only if portfolio owns it."""
    try:
        get_demo(demo_id)
    except KeyError:
        raise HTTPException(404, f"unknown demo: {demo_id}")
    current = get_state(demo_id)
    if current.session_id != body.session_id:
        return {"released": False, "reason": "session mismatch"}
    if current.started_by != "portfolio":
        return {"released": False, "reason": "not portfolio-owned"}
    try:
        stop_vm(demo_id)
    except Exception:
        logger.exception("release: stop failed for %s", demo_id)
        raise HTTPException(502, "failed to stop VM")
    update_state(demo_id, started_by=None, session_id=None, session_last_seen=None)
    return {"released": True}