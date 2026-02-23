"""Configuration models and loading helpers for the local middleware service.

This module keeps all config parsing in one place so app/policy code can rely on
strongly typed data structures. The primary source is a YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PiShockCredentials:
    """Credentials and target metadata needed for legacy PiShock HTTP calls."""

    username: str
    apikey: str
    code: str
    name: str = "CyberpunkBridge"


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

    pishock = PiShockCredentials(**raw["pishock"])
    service = raw["service"]

    return ServiceConfig(
        bind_host=service.get("bind_host", "127.0.0.1"),
        bind_port=int(service.get("bind_port", 8787)),
        shared_secret=service["shared_secret"],
        dry_run=bool(service.get("dry_run", True)),
        allow_shock=bool(service.get("allow_shock", False)),
        max_intensity=int(service.get("max_intensity", 20)),
        max_duration_ms=int(service.get("max_duration_ms", 2000)),
        default_cooldown_ms=int(service.get("default_cooldown_ms", 1500)),
        session_max_shock_level=int(service.get("session_max_shock_level", 100)),
        pishock=pishock,
        event_mappings=raw.get("event_mappings", {}),
    )
