"""Loads .env + demos.yaml into typed objects. Cached, fails fast on missing config."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()


class DemoConfig(BaseModel):
    id: str
    name: str
    instance: str
    zone: str
    healthUrl: str
    appUrl: str
    idleMinutes: int = 10


class AppConfig(BaseModel):
    gcp_project_id: str
    demos_config_path: str = "./demos.yaml"
    state_file_path: str = "./state.json"
    state_bucket: str = ""  # if set, overrides state_file_path with a GCS object
    admin_token: str
    default_idle_minutes: int = 10
    port: int = 8080
    allowed_origins: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    try:
        origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
        return AppConfig(
            gcp_project_id=os.environ["GCP_PROJECT_ID"],
            demos_config_path=os.getenv("DEMOS_CONFIG_PATH", "./demos.yaml"),
            state_file_path=os.getenv("STATE_FILE_PATH", "./state.json"),
            state_bucket=os.getenv("STATE_BUCKET", ""),
            admin_token=os.environ["ADMIN_TOKEN"],
            default_idle_minutes=int(os.getenv("DEFAULT_IDLE_MINUTES", "10")),
            port=int(os.getenv("PORT", "8080")),
            allowed_origins=origins,
        )
    except KeyError as e:
        raise RuntimeError(f"Missing required env var: {e}") from e
    except ValidationError as e:
        raise RuntimeError(f"Config validation failed: {e}") from e


@lru_cache(maxsize=1)
def get_demos() -> Dict[str, DemoConfig]:
    path = Path(get_app_config().demos_config_path)
    if not path.exists():
        raise RuntimeError(f"demos config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    demos_raw = raw.get("demos", {})
    if not isinstance(demos_raw, dict) or not demos_raw:
        raise RuntimeError("demos.yaml must contain a non-empty 'demos:' mapping")
    result: Dict[str, DemoConfig] = {}
    for demo_id, fields in demos_raw.items():
        try:
            result[demo_id] = DemoConfig(id=demo_id, **fields)
        except ValidationError as e:
            raise RuntimeError(f"demo '{demo_id}' invalid: {e}") from e
    return result


def get_demo(demo_id: str) -> DemoConfig:
    demos = get_demos()
    if demo_id not in demos:
        raise KeyError(f"unknown demo: {demo_id}")
    return demos[demo_id]