"""Output sinks: where an approved action ends up.

`SimulatedOutput` is the default and only logs. `PiShockOutput` drives the real
device and is constructed only when the user explicitly enables live mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import ServiceConfig
from .policy import Action


@dataclass(frozen=True)
class OutputResult:
    ok: bool
    detail: str = ""


@dataclass
class SimulatedOutput:
    """Logs what would be sent and keeps a history (used by tests and demos)."""

    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("middleware.output"))
    history: list[tuple[str, Action]] = field(default_factory=list)
    name: str = "simulated"

    def send(self, action: Action, event: dict[str, Any]) -> OutputResult:
        self.history.append((event.get("event_type", "?"), action))
        self.logger.info(
            "[SIMULATED] %s intensity=%d duration_ms=%d (event=%s)",
            action.mode,
            action.intensity,
            action.duration_ms,
            event.get("event_type"),
        )
        return OutputResult(ok=True, detail="simulated")


class PiShockOutput:
    """Sends actions to the PiShock API. Only used in explicit live mode."""

    name = "live"

    def __init__(
        self,
        config: ServiceConfig,
        is_stopped: Callable[[], bool],
        sender: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if sender is None:
            from .pishock_http import send_pishock_http  # pylint: disable=import-outside-toplevel

            sender = send_pishock_http
        self.config = config
        self.is_stopped = is_stopped
        self.sender = sender
        self.logger = logger or logging.getLogger("middleware.output")

    def send(self, action: Action, event: dict[str, Any]) -> OutputResult:
        # Re-check the emergency stop immediately before touching hardware.
        if self.is_stopped():
            return OutputResult(ok=False, detail="emergency stop engaged")
        if action.mode == "shock" and not self.config.allow_shock:
            return OutputResult(ok=False, detail="shock not allowed by config")

        result = self.sender(
            mode=action.mode,
            intensity=min(action.intensity, self.config.max_intensity),
            duration_ms=min(action.duration_ms, self.config.max_duration_ms),
            username=self.config.pishock.username,
            apikey=self.config.pishock.apikey,
            code=action.target,
            name=self.config.pishock.name,
        )
        self.logger.info(
            "[LIVE] %s intensity=%d duration_ms=%d (event=%s) -> status=%s body=%s",
            action.mode,
            action.intensity,
            action.duration_ms,
            event.get("event_type"),
            result.status_code,
            str(result.body)[:200],
        )
        return OutputResult(ok=bool(result.ok), detail=str(result.body)[:200])
