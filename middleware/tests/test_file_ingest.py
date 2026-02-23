"""Tests for file-based outbox ingester."""

from __future__ import annotations

import hashlib
import hmac
import json

from middleware import file_ingest
from middleware.config import PiShockCredentials, ServiceConfig
from middleware.policy import PolicyEngine


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


def _cfg() -> ServiceConfig:
    return ServiceConfig(
        bind_host="127.0.0.1",
        bind_port=8787,
        shared_secret="test-secret",
        dry_run=True,
        allow_shock=True,
        max_intensity=100,
        max_duration_ms=2000,
        default_cooldown_ms=0,
        session_max_shock_level=100,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={"player_damaged": {"mode": "shock", "duration_ms": 500, "cooldown_ms": 0}},
    )


def _signed_line(payload: dict, secret: str = "test-secret") -> str:
    body = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{sig}\t{body}\n"


def test_process_line_accepts_valid_signature():
    cfg = _cfg()
    policy = PolicyEngine(cfg)
    logger = DummyLogger()

    line = _signed_line(
        {
            "event_type": "player_damaged",
            "armed": True,
            "context": {"damage": 100, "max_health": 400},
        }
    )

    assert file_ingest._process_line(line, policy, cfg, logger) is True


def test_process_line_rejects_invalid_signature():
    cfg = _cfg()
    policy = PolicyEngine(cfg)
    logger = DummyLogger()

    payload = {
        "event_type": "player_damaged",
        "armed": True,
        "context": {"damage": 100, "max_health": 400},
    }
    body = json.dumps(payload, separators=(",", ":"))
    line = f"deadbeef\t{body}\n"

    assert file_ingest._process_line(line, policy, cfg, logger) is False


def test_offset_helpers_roundtrip(tmp_path):
    p = tmp_path / "offset.txt"
    assert file_ingest._load_offset(p) == 0
    file_ingest._save_offset(p, 123)
    assert file_ingest._load_offset(p) == 123
