"""End-to-end middleware request simulation tests.

These tests simulate real signed event submissions and validate expected output.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from middleware.app import create_app
from middleware.config import PiShockCredentials, ServiceConfig


def _build_cfg() -> ServiceConfig:
    """Build config fixture for dry-run API simulation tests."""

    return ServiceConfig(
        bind_host="127.0.0.1",
        bind_port=8787,
        shared_secret="test-secret",
        dry_run=True,
        allow_shock=True,
        max_intensity=100,
        max_duration_ms=2000,
        default_cooldown_ms=1500,
        session_max_shock_level=100,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={
            "player_damaged": {
                "mode": "shock",
        allow_shock=False,
        max_intensity=20,
        max_duration_ms=2000,
        default_cooldown_ms=1500,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={
            "player_damaged": {
                "mode": "vibrate",
                "intensity": 12,
                "duration_ms": 600,
                "cooldown_ms": 0,
            }
        },
    )


def _sign(secret: str, payload: dict) -> tuple[bytes, str]:
    """Build deterministic JSON body and matching HMAC signature."""

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


def test_post_event_simulation_returns_expected_action():
    """Simulate a valid event and verify accepted dry-run output payload."""

    client = TestClient(create_app(_build_cfg()))
    event = {
        "event_type": "player_damaged",
        "ts_ms": 1700000000000,
        "session_id": "session-1",
        "armed": True,
        "context": {"source": "cet", "damage": 100, "max_health": 400},
        "armed": False,
        "context": {"source": "cet"},
    }
    body, signature = _sign("test-secret", event)

    resp = client.post(
        "/event",
        data=body,
        headers={"content-type": "application/json", "X-Event-Signature": signature},
    )

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] is True
    assert data["dry_run"] is True
    assert data["action"]["mode"] == "shock"
    assert data["action"]["intensity"] == 25
    assert data["action"]["mode"] == "vibrate"
    assert data["action"]["intensity"] == 12
