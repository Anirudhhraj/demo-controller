"""FastAPI entry point. Wires routes, CORS, and logging."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_app_config, get_demos
from app.routes import admin as admin_routes
from app.routes import demos as demo_routes


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "info").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    _configure_logging()
    cfg = get_app_config()
    _ = get_demos()  # fail fast on bad demos.yaml

    app = FastAPI(title="Demo Controller", version="0.1.0")

    if cfg.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*", "X-Admin-Token"],
        )

    app.include_router(demo_routes.router)
    app.include_router(admin_routes.router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


app = create_app()