"""Per-demo lifecycle state.

Backend is chosen at runtime:
  - if STATE_BUCKET env is set: GCS object at gs://<bucket>/state.json
  - otherwise:                  local JSON file at STATE_FILE_PATH

The public surface (get / update / list_all / now_iso) is identical for both.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from app.config import get_app_config

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_OBJECT_NAME = "state.json"


@dataclass
class DemoState:
    started_by: Optional[str] = None
    session_id: Optional[str] = None
    session_last_seen: Optional[str] = None
    locked_until: Optional[str] = None
    last_action: Optional[str] = None


_KNOWN_FIELDS = set(DemoState.__annotations__.keys())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_state(raw: dict) -> DemoState:
    return DemoState(**{k: raw.get(k) for k in _KNOWN_FIELDS})


# --------- Backends ---------
class _FileBackend:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def read_all(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            logger.exception("state file corrupted, returning empty")
            return {}

    def write_all(self, data: Dict[str, dict]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)


class _GcsBackend:
    def __init__(self, bucket_name: str, project: str) -> None:
        from google.cloud import storage  # imported lazily so tests don't need GCS
        self._client = storage.Client(project=project)
        self._bucket = self._client.bucket(bucket_name)

    def read_all(self) -> Dict[str, dict]:
        from google.api_core import exceptions as gcp_exceptions
        blob = self._bucket.blob(_OBJECT_NAME)
        try:
            data = json.loads(blob.download_as_bytes())
            return data if isinstance(data, dict) else {}
        except gcp_exceptions.NotFound:
            return {}
        except (json.JSONDecodeError, ValueError):
            logger.exception("state object corrupted, returning empty")
            return {}

    def write_all(self, data: Dict[str, dict]) -> None:
        blob = self._bucket.blob(_OBJECT_NAME)
        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")


_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        cfg = get_app_config()
        if cfg.state_bucket:
            _backend = _GcsBackend(cfg.state_bucket, cfg.gcp_project_id)
            logger.info("state backend: GCS bucket %s", cfg.state_bucket)
        else:
            _backend = _FileBackend(cfg.state_file_path)
            logger.info("state backend: local file %s", cfg.state_file_path)
    return _backend


def _reset_backend_for_tests() -> None:
    global _backend
    _backend = None


# --------- Public API (unchanged) ---------
def get(demo_id: str) -> DemoState:
    with _lock:
        return _to_state(_get_backend().read_all().get(demo_id, {}))


def update(demo_id: str, **changes) -> DemoState:
    unknown = set(changes) - _KNOWN_FIELDS
    if unknown:
        raise ValueError(f"unknown state fields: {unknown}")
    with _lock:
        backend = _get_backend()
        all_data = backend.read_all()
        current = all_data.get(demo_id, {})
        current.update(changes)
        current["last_action"] = now_iso()
        all_data[demo_id] = current
        backend.write_all(all_data)
        return _to_state(current)


def list_all() -> Dict[str, DemoState]:
    with _lock:
        return {k: _to_state(v) for k, v in _get_backend().read_all().items()}