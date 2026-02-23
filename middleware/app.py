"""FastAPI application for local Cyberpunk event ingestion.

Design goals:
- localhost-only deployment by default
- HMAC request authentication for every event
- strict policy evaluation before any PiShock actuation
"""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .config import ServiceConfig, load_config
from .pishock_http import send_pishock_http
from .policy import CooldownError, PolicyEngine, PolicyError
from .security import verify_signature

VERSION = "0.2.0"


class JsonFormatter(logging.Formatter):
    """Serialize log records as JSON for easier filtering and ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "ts": int(record.created * 1000),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    """Configure stdout + rotating file logs.

    Handler setup is idempotent to avoid duplicate logs when app reloads.
    """

    logger = logging.getLogger("middleware")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = JsonFormatter()
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)

    Path("logs").mkdir(exist_ok=True)
    fh = RotatingFileHandler("logs/middleware.log", maxBytes=1_000_000, backupCount=3)
    fh.setFormatter(formatter)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


def create_app(config: ServiceConfig) -> FastAPI:
    """Create a configured FastAPI app instance."""

    logger = configure_logging()
    policy_engine = PolicyEngine(config)
    app = FastAPI(title="Cyberpunk PiShock Middleware", version=VERSION)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Basic service health endpoint."""

        return {"status": "ok", "version": VERSION}

    @app.post("/event", status_code=202)
    async def ingest_event(request: Request) -> dict[str, Any]:
        """Receive signed game events, apply policy, and optionally actuate PiShock."""

        body = await request.body()
        signature = request.headers.get("X-Event-Signature")
        if not verify_signature(body, signature, config.shared_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            event = await request.json()
            action = policy_engine.decide(event)
        except CooldownError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except (PolicyError, KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info("event_accepted event_type=%s action=%s", event.get("event_type"), action)

        if config.dry_run:
            logger.info(
                "dry_run: would_send mode=%s intensity=%s duration_ms=%s",
                action.mode,
                action.intensity,
                action.duration_ms,
            )
            return {"accepted": True, "dry_run": True, "action": action.__dict__}

        result = send_pishock_http(
            mode=action.mode,
            intensity=action.intensity,
            duration_ms=action.duration_ms,
            username=config.pishock.username,
            apikey=config.pishock.apikey,
            code=action.target,
            name=config.pishock.name,
        )
        logger.info("pishock_response ok=%s status=%s body=%s", result.ok, result.status_code, result.body)
        if not result.ok:
            raise HTTPException(status_code=502, detail="PiShock request failed")

        return {"accepted": True, "dry_run": False, "action": action.__dict__}

    return app


def load_runtime_config() -> ServiceConfig:
    """Load config from `MIDDLEWARE_CONFIG` or the example fallback path."""

    cfg_path = os.getenv("MIDDLEWARE_CONFIG", "middleware/config.example.yaml")
    return load_config(cfg_path)


app = create_app(load_runtime_config())
