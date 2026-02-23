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

    def _damage_scaled_shock_intensity(self, event: dict[str, Any]) -> int:
        """Compute shock intensity as damage% * session max shock level.

        Expected event context fields:
        - damage: damage value taken
        - max_health: actor max health pool

        Example: damage=100, max_health=400, session_max_shock_level=100 -> 25.
        """

        context = event.get("context") or {}
        damage = float(context["damage"])
        max_health = float(context["max_health"])
        if max_health <= 0:
            raise PolicyError("context.max_health must be > 0 for damage-based shock")

        damage_ratio = max(0.0, min(1.0, damage / max_health))
        return int(round(damage_ratio * self.config.session_max_shock_level))

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

        # For damage events mapped to shock, scale intensity by damage percentage.
        if mode == "shock" and event_type == "player_damaged":
            try:
                intensity = self._damage_scaled_shock_intensity(event)
            except (KeyError, TypeError, ValueError) as exc:
                raise PolicyError(
                    "player_damaged shock requires numeric context.damage and context.max_health"
                ) from exc

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
