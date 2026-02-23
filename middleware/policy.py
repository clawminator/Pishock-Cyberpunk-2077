"""Policy engine for mapping events to safe PiShock actions.

This module is the core safety boundary: allowlist-driven event mapping,
anti-spam cooldowns, and hard caps for intensity/duration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .config import ServiceConfig


@dataclass(frozen=True)
class Action:
    """Resolved action after policy evaluation."""

    mode: str
    intensity: int
    duration_ms: int
    target: str


class PolicyError(Exception):
    """Raised when an event is invalid or disallowed by policy."""


class CooldownError(PolicyError):
    """Raised when an event is denied due to cooldown/rate-limiting."""


class PolicyEngine:
    """Applies event mappings, safety constraints, and cooldown logic."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        # Keyed by (event_type, target). Value is last accepted timestamp in ms.
        self._last_fired_ms: dict[tuple[str, str], int] = {}

    def decide(self, event: dict[str, Any]) -> Action:
        """Return an allowed action or raise a policy-related exception."""

        event_type = event["event_type"]
        mapping = self.config.event_mappings.get(event_type)
        if not mapping:
            raise PolicyError(f"No mapping for event_type={event_type}")

        mode = mapping.get("mode", "beep")
        intensity = int(mapping.get("intensity", 1))
        duration_ms = int(mapping.get("duration_ms", 300))
        target = mapping.get("target", self.config.pishock.code)

        # Shock requires explicit global opt-in and per-event armed status.
        if mode == "shock" and (not self.config.allow_shock or not event.get("armed", False)):
            raise PolicyError("Shock mode is disabled or event is not armed")

        # Hard caps prevent unsafe or invalid values from config mistakes.
        intensity = min(max(1, intensity), self.config.max_intensity)
        duration_ms = min(max(100, duration_ms), self.config.max_duration_ms)

        cooldown_ms = int(mapping.get("cooldown_ms", self.config.default_cooldown_ms))
        now_ms = int(time.time() * 1000)
        key = (event_type, target)
        last = self._last_fired_ms.get(key)
        if last is not None and now_ms - last < cooldown_ms:
            raise CooldownError(f"Cooldown active for {event_type}")

        self._last_fired_ms[key] = now_ms
        return Action(mode=mode, intensity=intensity, duration_ms=duration_ms, target=target)
