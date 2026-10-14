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

from middleware.app import create_app  # noqa: E402
from middleware.config import PiShockCredentials, SafetyConfig, ServiceConfig  # noqa: E402


def _build_cfg(tmp_path, **overrides) -> ServiceConfig:
    """Build config fixture for dry-run API simulation tests."""

    values = dict(
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
            "player_damaged": {"mode": "shock", "intensity": 8, "duration_ms": 400, "cooldown_ms": 0},
            "player_healed": {"mode": "vibrate", "intensity": 12, "duration_ms": 600, "cooldown_ms": 0},
        },
        safety=SafetyConfig(estop_file=str(tmp_path / "ESTOP"), global_cooldown_ms=0),
    )
    values.update(overrides)
    return ServiceConfig(**values)


def _sign(secret: str, payload: dict) -> tuple[bytes, str]:
    """Build deterministic JSON body and matching HMAC signature."""

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


def _post(client, payload, secret="test-secret"):
    body, signature = _sign(secret, payload)
    return client.post(
        "/event",
        content=body,
        headers={"content-type": "application/json", "X-Event-Signature": signature},
    )


DAMAGE_EVENT = {
    "event_type": "player_damaged",
    "ts_ms": 1700000000000,
    "session_id": "session-1",
    "armed": True,
    "context": {"source": "cet", "damage": 100, "max_health": 400},
}


def test_post_event_simulation_returns_expected_action(tmp_path):
    """Damage 100/400 with session max 100 -> shock intensity 25 (dry run)."""

    client = TestClient(create_app(_build_cfg(tmp_path)))
    resp = _post(client, DAMAGE_EVENT)

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] is True
    assert data["dry_run"] is True
    assert data["action"]["mode"] == "shock"
    assert data["action"]["intensity"] == 25


def test_vibrate_event(tmp_path):
    client = TestClient(create_app(_build_cfg(tmp_path)))
    resp = _post(client, {"event_type": "player_healed", "armed": False, "context": {"source": "cet"}})
    assert resp.status_code == 202
    assert resp.json()["action"] == {"mode": "vibrate", "intensity": 12, "duration_ms": 600, "target": "c"}


def test_bad_signature_rejected(tmp_path):
    client = TestClient(create_app(_build_cfg(tmp_path)))
    assert _post(client, DAMAGE_EVENT, secret="wrong").status_code == 401


def test_unarmed_shock_rejected(tmp_path):
    client = TestClient(create_app(_build_cfg(tmp_path)))
    assert _post(client, {**DAMAGE_EVENT, "armed": False}).status_code == 400


def test_emergency_stop_blocks_http_path(tmp_path):
    (tmp_path / "ESTOP").write_text("test", encoding="utf-8")
    client = TestClient(create_app(_build_cfg(tmp_path)))
    assert client.get("/health").json()["estop"] is True
    assert _post(client, DAMAGE_EVENT).status_code == 423


def test_global_rate_limit_applies_to_http_path(tmp_path):
    cfg = _build_cfg(tmp_path, safety=SafetyConfig(estop_file=str(tmp_path / "ESTOP"), max_actions_per_minute=2, global_cooldown_ms=0))
    client = TestClient(create_app(cfg))
    codes = [_post(client, {"event_type": "player_healed", "context": {}}).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
