"""Configuration models and loading helpers for the local middleware service.

This module keeps all config parsing in one place so app/policy code can rely on
strongly typed data structures. The primary source is a YAML file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Hard device limits. Config values are clamped into these ranges no matter
# what the YAML says.
PISHOCK_MAX_INTENSITY = 100
PISHOCK_MAX_DURATION_MS = 15_000
MIN_DURATION_MS = 100

VALID_MODES = ("shock", "vibrate", "beep")

DEFAULT_OUTBOX_PATH = "emitter/cet/mods/pishock_emitter/outbox/events.jsonl"
DEFAULT_ESTOP_PATH = "middleware/state/ESTOP"

# The repository checkout. Relative paths in a config file resolve against
# this, not the working directory, so every command (consumer, e-stop CLI,
# simulator) agrees on the same files no matter where it is started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

LOCAL_CONFIG = PROJECT_ROOT / "middleware" / "config.local.yaml"
EXAMPLE_CONFIG = PROJECT_ROOT / "middleware" / "config.example.yaml"


def resolve_path(value: str | Path) -> str:
    """Anchor a config path at PROJECT_ROOT unless it is already absolute."""

    path = Path(value).expanduser()
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def default_config_path() -> str:
    """The config every CLI uses when --config is not given.

    $MIDDLEWARE_CONFIG, else the setup wizard's config.local.yaml if it
    exists, else config.example.yaml. Shared so the consumer and
    `middleware-estop` cannot silently pick different configs.
    """

    env = os.getenv("MIDDLEWARE_CONFIG")
    if env:
        return env
    return str(LOCAL_CONFIG if LOCAL_CONFIG.exists() else EXAMPLE_CONFIG)


class ConfigError(ValueError):
    """Raised when a config file is structurally invalid."""


@dataclass(frozen=True)
class PiShockCredentials:
    """Credentials and target metadata needed for legacy PiShock HTTP calls."""

    username: str
    apikey: str
    code: str
    name: str = "CyberpunkBridge"


@dataclass(frozen=True)
class SafetyConfig:
    """Consumer-side safety limits applied on top of the policy engine."""

    # Global rate limit across all events (sliding 60 s window).
    max_actions_per_minute: int = 20
    # Minimum gap between any two outputs, regardless of event type.
    global_cooldown_ms: int = 500
    # Events older (or newer) than this are dropped; 0 disables the check.
    max_event_age_s: float = 10.0
    # While this file exists, no output is produced.
    estop_file: str = resolve_path(DEFAULT_ESTOP_PATH)


@dataclass(frozen=True)
class IngestConfig:
    """Where the file consumer reads events from."""

    outbox_path: str = resolve_path(DEFAULT_OUTBOX_PATH)
    poll_interval_s: float = 0.1


@dataclass(frozen=True)
class ServiceConfig:
    """Top-level service configuration loaded from YAML."""

    bind_host: str
    bind_port: int
    shared_secret: str
    dry_run: bool
    allow_shock: bool
    max_intensity: int
    max_duration_ms: int
    default_cooldown_ms: int
    # Session cap used by damage->shock scaling. If set to 100, a 25% damage event
    # can result in intensity 25 at most.
    session_max_shock_level: int
    pishock: PiShockCredentials
    event_mappings: dict[str, dict[str, Any]]
    # Send vibrate/beep under 1.5 s in milliseconds instead of whole seconds.
    # Undocumented in the PiShock API, so opt-in; never used for shock.
    subsecond_vibrate_beep: bool = False
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _as_bool(value: Any, key: str) -> bool:
    """Parse a YAML boolean strictly. `bool("false")` is True, so a quoted
    `allow_shock: "false"` must not be passed through bool()."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "on", "1"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "off", "0"):
        return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ConfigError(f"service.{key} must be true or false, got {value!r}")


def _validate_mappings(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("event_mappings must be a mapping of event_type -> settings")
    mappings: dict[str, dict[str, Any]] = {}
    for event_type, mapping in raw.items():
        if not isinstance(mapping, dict):
            raise ConfigError(f"event_mappings.{event_type} must be a mapping")
        mode = mapping.get("mode", "beep")
        if mode not in VALID_MODES:
            raise ConfigError(f"event_mappings.{event_type}.mode must be one of {VALID_MODES}, got {mode!r}")
        fallback = mapping.get("fallback_mode")
        if fallback is not None and fallback not in ("vibrate", "beep"):
            raise ConfigError(f"event_mappings.{event_type}.fallback_mode must be vibrate or beep")
        mappings[str(event_type)] = dict(mapping)
    return mappings


def load_config(path: str | Path) -> ServiceConfig:
    """Load and validate middleware YAML config.

    Import is intentionally lazy so modules depending on dataclasses can be used
    in test/simulation contexts even when optional runtime deps are unavailable.
    """

    try:
        import yaml  # pylint: disable=import-outside-toplevel
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyYAML is required to load middleware config files") from exc

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "service" not in raw or "pishock" not in raw:
        raise ConfigError(f"{path}: config must contain 'service' and 'pishock' sections")

    pishock = PiShockCredentials(**{k: str(v) for k, v in raw["pishock"].items()})
    service = raw["service"]

    shared_secret = service.get("shared_secret")
    if not shared_secret:
        raise ConfigError("service.shared_secret must be set")

    safety_raw = raw.get("safety") or {}
    safety = SafetyConfig(
        max_actions_per_minute=max(1, int(safety_raw.get("max_actions_per_minute", 20))),
        global_cooldown_ms=max(0, int(safety_raw.get("global_cooldown_ms", 500))),
        max_event_age_s=max(0.0, float(safety_raw.get("max_event_age_s", 10.0))),
        estop_file=resolve_path(safety_raw.get("estop_file", DEFAULT_ESTOP_PATH)),
    )
    ingest_raw = raw.get("ingest") or {}
    ingest = IngestConfig(
        outbox_path=resolve_path(ingest_raw.get("outbox_path", DEFAULT_OUTBOX_PATH)),
        poll_interval_s=max(0.02, float(ingest_raw.get("poll_interval_s", 0.1))),
    )

    return ServiceConfig(
        bind_host=service.get("bind_host", "127.0.0.1"),
        bind_port=int(service.get("bind_port", 8787)),
        shared_secret=str(shared_secret),
        dry_run=_as_bool(service.get("dry_run", True), "dry_run"),
        allow_shock=_as_bool(service.get("allow_shock", False), "allow_shock"),
        max_intensity=_clamp(int(service.get("max_intensity", 20)), 1, PISHOCK_MAX_INTENSITY),
        max_duration_ms=_clamp(int(service.get("max_duration_ms", 2000)), MIN_DURATION_MS, PISHOCK_MAX_DURATION_MS),
        default_cooldown_ms=max(0, int(service.get("default_cooldown_ms", 1500))),
        session_max_shock_level=_clamp(int(service.get("session_max_shock_level", 100)), 1, PISHOCK_MAX_INTENSITY),
        pishock=pishock,
        event_mappings=_validate_mappings(raw.get("event_mappings")),
        subsecond_vibrate_beep=_as_bool(service.get("subsecond_vibrate_beep", False), "subsecond_vibrate_beep"),
        safety=safety,
        ingest=ingest,
    )
