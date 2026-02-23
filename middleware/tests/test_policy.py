"""Policy engine unit tests for safety and cap behavior."""

from middleware.config import PiShockCredentials, ServiceConfig
from middleware.policy import PolicyEngine, PolicyError


def make_cfg() -> ServiceConfig:
    """Build a minimal in-memory config fixture."""

    return ServiceConfig(
        bind_host="127.0.0.1",
        bind_port=8787,
        shared_secret="secret",
        dry_run=True,
        allow_shock=False,
        max_intensity=20,
        max_duration_ms=2000,
        default_cooldown_ms=1500,
        pishock=PiShockCredentials(username="u", apikey="k", code="c"),
        event_mappings={"evt": {"mode": "vibrate", "intensity": 99, "duration_ms": 99999}},
    )


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

    try:
        pe.decide({"event_type": "shock_evt", "armed": True})
        assert False, "expected PolicyError"
    except PolicyError:
        pass
