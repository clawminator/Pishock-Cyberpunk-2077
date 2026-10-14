"""Shared fixtures."""

from __future__ import annotations

import pytest

from middleware.config import PiShockCredentials, SafetyConfig, ServiceConfig


def make_config(**overrides) -> ServiceConfig:
    """In-memory config with test-friendly defaults (no cooldowns, no rate limit)."""

    values = dict(
        bind_host="127.0.0.1",
        bind_port=8787,
        shared_secret="test-secret",
        dry_run=True,
        allow_shock=False,
        max_intensity=20,
        max_duration_ms=2000,
        default_cooldown_ms=0,
        session_max_shock_level=100,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={
            "player_damaged": {"mode": "shock", "fallback_mode": "vibrate", "intensity": 8, "duration_ms": 400, "cooldown_ms": 0},
            "player_healed": {"mode": "vibrate", "intensity": 10, "duration_ms": 500, "cooldown_ms": 0},
            "player_death": {"mode": "beep", "intensity": 1, "duration_ms": 1000, "cooldown_ms": 0},
            "combat_start": {"mode": "vibrate", "intensity": 6, "duration_ms": 300, "cooldown_ms": 0},
            "quest_completed": {"mode": "vibrate", "intensity": 14, "duration_ms": 700, "cooldown_ms": 0},
            "test_pulse": {"mode": "beep", "intensity": 1, "duration_ms": 300, "cooldown_ms": 0},
        },
        safety=SafetyConfig(max_actions_per_minute=1000, global_cooldown_ms=0, max_event_age_s=10.0),
    )
    values.update(overrides)
    return ServiceConfig(**values)


@pytest.fixture
def cfg_factory():
    return make_config


@pytest.fixture
def lua():
    """LuaJIT runtime with the emitter's lib/ on package.path (skips without lupa)."""

    pytest.importorskip("lupa")
    from middleware.tests.cet_harness import make_lua  # pylint: disable=import-outside-toplevel

    return make_lua()


@pytest.fixture
def cet(tmp_path, monkeypatch):
    """The real CET emitter in a temp mod dir under a fake CET API (skips without lupa)."""

    pytest.importorskip("lupa")
    from middleware.tests.cet_harness import CetHarness, make_mod_copy  # pylint: disable=import-outside-toplevel

    mod_dir = make_mod_copy(tmp_path)
    monkeypatch.chdir(mod_dir)  # CET resolves io.open relative to the mod dir
    return CetHarness(mod_dir)
