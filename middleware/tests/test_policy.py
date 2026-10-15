"""Policy engine unit tests for safety and cap behavior."""

import pytest

from middleware.config import PiShockCredentials, ServiceConfig
from middleware.policy import CooldownError, PolicyEngine, PolicyError


def make_cfg(**overrides) -> ServiceConfig:
    """Build a minimal in-memory config fixture."""

    values = dict(
        bind_host="127.0.0.1",
        bind_port=8787,
        shared_secret="secret",
        dry_run=True,
        allow_shock=False,
        max_intensity=20,
        max_duration_ms=2000,
        default_cooldown_ms=1500,
        session_max_shock_level=100,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={"evt": {"mode": "vibrate", "intensity": 99, "duration_ms": 99999}},
    )
    values.update(overrides)
    return ServiceConfig(**values)


def test_caps_are_enforced():
    """Intensity and duration values must be clamped to configured caps."""

    pe = PolicyEngine(make_cfg())
    act = pe.decide({"event_type": "evt", "armed": False})
    assert act.intensity == 20
    assert act.duration_ms == 2000


def test_shock_disabled_by_default():
    """Shock actions are denied unless explicitly enabled and armed."""

    cfg = make_cfg()
    cfg.event_mappings["shock_evt"] = {"mode": "shock", "intensity": 5, "duration_ms": 300}
    pe = PolicyEngine(cfg)

    with pytest.raises(PolicyError):
        pe.decide({"event_type": "shock_evt", "armed": True})


def test_shock_requires_armed_even_when_allowed():
    cfg = make_cfg(allow_shock=True, event_mappings={"s": {"mode": "shock", "intensity": 5}})
    pe = PolicyEngine(cfg)
    for armed in (False, None, "true", 1):
        with pytest.raises(PolicyError):
            pe.decide({"event_type": "s", "armed": armed}, now_ms=0)
    assert pe.decide({"event_type": "s", "armed": True}, now_ms=0).mode == "shock"


def test_damage_percentage_scales_shock_intensity():
    """Damage ratio should scale intensity by session_max_shock_level."""

    cfg = make_cfg(allow_shock=True, event_mappings={"player_damaged": {"mode": "shock", "intensity": 1, "duration_ms": 300}})
    pe = PolicyEngine(cfg)
    act = pe.decide({"event_type": "player_damaged", "armed": True, "context": {"damage": 100, "max_health": 400}})
    assert act.intensity == 20  # 25 scaled, then capped by max_intensity=20


def test_damage_scaling_uses_session_level():
    cfg = make_cfg(
        allow_shock=True,
        session_max_shock_level=40,
        event_mappings={"player_damaged": {"mode": "shock", "intensity": 1, "duration_ms": 300}},
    )
    act = PolicyEngine(cfg).decide({"event_type": "player_damaged", "armed": True, "context": {"damage": 100, "max_health": 400}})
    assert act.intensity == 10


def test_damage_shock_without_context_is_rejected():
    cfg = make_cfg(allow_shock=True, event_mappings={"player_damaged": {"mode": "shock"}})
    with pytest.raises(PolicyError):
        PolicyEngine(cfg).decide({"event_type": "player_damaged", "armed": True})


def test_shock_falls_back_to_vibrate_when_not_permitted():
    mapping = {"player_damaged": {"mode": "shock", "fallback_mode": "vibrate", "intensity": 8, "duration_ms": 400}}
    event = {"event_type": "player_damaged", "armed": True, "context": {"damage": 40, "max_health": 400}}

    act = PolicyEngine(make_cfg(event_mappings=mapping)).decide(event)  # allow_shock false
    assert act.mode == "vibrate" and act.intensity == 10

    act = PolicyEngine(make_cfg(allow_shock=True, event_mappings=mapping)).decide({**event, "armed": False})
    assert act.mode == "vibrate"

    act = PolicyEngine(make_cfg(allow_shock=True, event_mappings=mapping)).decide(event)
    assert act.mode == "shock"


def test_unmapped_event_rejected():
    with pytest.raises(PolicyError, match="No mapping"):
        PolicyEngine(make_cfg()).decide({"event_type": "nope"})


def test_cooldown_per_event():
    cfg = make_cfg(event_mappings={"evt": {"mode": "beep", "cooldown_ms": 1000}})
    pe = PolicyEngine(cfg)
    pe.decide({"event_type": "evt"}, now_ms=10_000)
    with pytest.raises(CooldownError):
        pe.decide({"event_type": "evt"}, now_ms=10_500)
    pe.decide({"event_type": "evt"}, now_ms=11_000)
