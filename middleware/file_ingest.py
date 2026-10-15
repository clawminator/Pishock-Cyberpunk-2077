"""File-based event consumer for the CET emitter's JSONL outbox.

Pipeline for every new line:

    parse -> (emergency_stop? latch) -> verify HMAC -> info event? -> stale?
          -> e-stop engaged? -> policy engine -> global rate limit -> output

Output is simulated unless the user explicitly enables live hardware with both
``dry_run: false`` in the config *and* ``--live`` on the command line.

The consumer only reads lines appended after it starts, so old events are
never replayed into hardware. It also writes ``consumer_status.txt`` next to
the outbox so the in-game overlay can show its state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import ServiceConfig, load_config
from .policy import CooldownError, PolicyEngine, PolicyError
from .protocol import parse_line
from .safety import EmergencyStop, RateLimiter
from .security import verify_signature

# Events that carry state, not actions. They are logged and never mapped.
INFO_EVENTS = frozenset(
    {"emitter_ready", "emitter_shutdown", "armed_changed", "combat_end", "emergency_stop_cleared"}
)

STATUS_FILENAME = "consumer_status.txt"


class Output(Protocol):
    name: str

    def send(self, action: Any, event: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class Outcome:
    """What happened to a line. `status` is sent / info / estop / skipped."""

    status: str
    reason: str = ""
    event_type: str | None = None
    action: Any = None


class OutboxTailer:
    """Follows an append-only file, yielding only complete lines.

    Handles the emitter truncating the file (game restart, mod reload, size
    cap): a shrink, or a change in the bytes just before our offset, resets
    reading to the start of the file.
    """

    FINGERPRINT_BYTES = 64

    def __init__(self, path: Path, start_at_end: bool = True) -> None:
        self.path = Path(path)
        self.start_at_end = start_at_end
        self.offset: int | None = None
        self.resets = 0
        self._partial = b""
        self._fingerprint = b""

    def _reset(self) -> None:
        self.offset = 0
        self._partial = b""
        self._fingerprint = b""
        self.resets += 1

    def poll(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            # Anything written to a file that did not exist yet is new.
            if self.offset is None:
                self.offset = 0
            return []

        if self.offset is None:
            self.offset = size if self.start_at_end else 0
            if self.offset:
                start = max(0, self.offset - self.FINGERPRINT_BYTES)
                with self.path.open("rb") as handle:
                    handle.seek(start)
                    self._fingerprint = handle.read(self.offset - start)

        if size < self.offset:
            self._reset()

        with self.path.open("rb") as handle:
            if self._fingerprint:
                handle.seek(self.offset - len(self._fingerprint))
                if handle.read(len(self._fingerprint)) != self._fingerprint:
                    self._reset()
            handle.seek(self.offset)
            data = handle.read()

        if not data:
            return []
        self.offset += len(data)
        consumed = self._partial + data
        self._fingerprint = consumed[-self.FINGERPRINT_BYTES:]
        *complete, self._partial = consumed.split(b"\n")
        return [raw.decode("utf-8", "surrogateescape").rstrip("\r") for raw in complete if raw.strip()]


class Ingester:
    """Applies verification, safety checks and policy to outbox lines."""

    def __init__(
        self,
        config: ServiceConfig,
        output: Output,
        estop: EmergencyStop | None = None,
        clock: Callable[[], float] = time.time,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.output = output
        self.estop = estop or EmergencyStop(config.safety.estop_file)
        self.clock = clock
        self.logger = logger or logging.getLogger("middleware.file_ingest")
        self.policy = PolicyEngine(config)
        self.rate = RateLimiter(config.safety.max_actions_per_minute, config.safety.global_cooldown_ms)
        self.counts: dict[str, int] = {}
        self.last_summary = "-"

    def _count(self, outcome: Outcome) -> Outcome:
        key = outcome.status if outcome.status != "skipped" else f"skipped:{outcome.reason}"
        self.counts[key] = self.counts.get(key, 0) + 1
        return outcome

    def _skip(self, reason: str, event_type: str | None = None, level: int = logging.WARNING) -> Outcome:
        self.logger.log(level, "skip reason=%s event_type=%s", reason, event_type)
        return self._count(Outcome("skipped", reason, event_type))

    def process_line(self, line: str) -> Outcome:
        parsed = parse_line(line)
        if parsed is None:
            return self._skip("malformed_line")

        try:
            event = json.loads(parsed.body)
        except json.JSONDecodeError:
            return self._skip("invalid_json")
        if not isinstance(event, dict) or not isinstance(event.get("event_type"), str):
            return self._skip("invalid_event")
        event_type = event["event_type"]

        # An emergency stop is honoured even if the signature does not verify:
        # stopping is always the safe direction.
        if event_type == "emergency_stop":
            self.estop.engage(f"in-game emergency stop (session={event.get('session_id')})")
            self.logger.critical("EMERGENCY STOP engaged by game event; clear with `middleware-estop --clear`")
            self.last_summary = "EMERGENCY STOP"
            return self._count(Outcome("estop", "engaged", event_type))

        if not verify_signature(parsed.body.encode("utf-8", "surrogateescape"), parsed.signature, self.config.shared_secret):
            return self._skip("invalid_signature", event_type)

        if event_type in INFO_EVENTS:
            self.logger.info("info event_type=%s armed=%s context=%s", event_type, event.get("armed"), event.get("context"))
            return self._count(Outcome("info", event_type=event_type))

        now_s = self.clock()
        max_age = self.config.safety.max_event_age_s
        if max_age > 0:
            ts_ms = event.get("ts_ms")
            if not isinstance(ts_ms, (int, float)):
                return self._skip("missing_ts", event_type)
            if abs(now_s - ts_ms / 1000.0) > max_age:
                return self._skip("stale_event", event_type)

        if self.estop.is_engaged():
            return self._skip("emergency_stop", event_type)

        try:
            action = self.policy.decide(event, now_ms=int(now_s * 1000))
        except CooldownError:
            return self._skip("cooldown", event_type, logging.INFO)
        except PolicyError as exc:
            reason = "unmapped" if str(exc).startswith("No mapping") else "policy"
            self.logger.log(logging.DEBUG if reason == "unmapped" else logging.WARNING, "policy detail=%s", exc)
            return self._count(Outcome("skipped", reason, event_type))
        except (KeyError, TypeError, ValueError) as exc:
            self.logger.warning("policy detail=%s", exc)
            return self._count(Outcome("skipped", "policy", event_type))

        limited = self.rate.check(now_s)
        if limited:
            return self._skip(limited, event_type, logging.INFO)

        result = self.output.send(action, event)
        # Recorded even on failure: a timed-out request may still have reached
        # the device, so it must count toward the global limits.
        self.rate.record(now_s)
        if not result.ok:
            return self._skip(f"output_failed:{result.detail}", event_type)
        self.last_summary = f"{event_type} -> {action.mode} {action.intensity}"
        return self._count(Outcome("sent", event_type=event_type, action=action))


def write_status(path: Path, ingester: Ingester, state: str) -> None:
    """Write the status file the in-game overlay reads. Best effort."""

    lines = [
        f"ts={int(time.time())}",
        f"state={state}",
        f"output={ingester.output.name}",
        f"estop={1 if ingester.estop.is_engaged() else 0}",
        f"sent={ingester.counts.get('sent', 0)}",
        f"last={ingester.last_summary}",
    ]
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # the game may have the file open for a moment; try again next tick


def run_ingest_loop(
    ingester: Ingester,
    outbox: Path,
    poll_interval_s: float = 0.1,
    from_start: bool = False,
    stop_after_s: float | None = None,
    status_path: Path | None = None,
) -> None:
    """Follow `outbox` forever (or for `stop_after_s`) feeding the ingester."""

    tailer = OutboxTailer(outbox, start_at_end=not from_start)
    status_path = status_path or outbox.parent / STATUS_FILENAME
    started = time.monotonic()
    next_status = 0.0
    try:
        while True:
            for line in tailer.poll():
                ingester.process_line(line)
            now = time.monotonic()
            if now >= next_status and status_path.parent.is_dir():
                write_status(status_path, ingester, "running")
                next_status = now + 1.0
            if stop_after_s is not None and now - started >= stop_after_s:
                break
            time.sleep(poll_interval_s)
    finally:
        if status_path.parent.is_dir():
            write_status(status_path, ingester, "stopped")


def _get_logger(verbose: bool) -> logging.Logger:
    root = logging.getLogger("middleware")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logging.getLogger("middleware.file_ingest")


def _confirm_live(config: ServiceConfig, assume_yes: bool) -> bool:
    print("=" * 64)
    print(" LIVE HARDWARE OUTPUT REQUESTED")
    print(f"   allow_shock={config.allow_shock}  max_intensity={config.max_intensity}"
          f"  max_duration_ms={config.max_duration_ms}")
    print(f"   rate limit={config.safety.max_actions_per_minute}/min"
          f"  global gap={config.safety.global_cooldown_ms} ms")
    print(f"   emergency stop: in-game hotkey, Ctrl+C, or create {config.safety.estop_file}")
    print("=" * 64)
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print("refusing live mode without a terminal; pass --yes to confirm non-interactively")
        return False
    try:
        return input('Type "LIVE" to enable hardware output: ').strip() == "LIVE"
    except EOFError:  # e.g. stdin is NUL, which Windows reports as a tty
        return False


def build_output(config: ServiceConfig, live: bool, estop: EmergencyStop, logger: logging.Logger) -> Output | None:
    from .output import PiShockOutput, SimulatedOutput  # pylint: disable=import-outside-toplevel

    if not live:
        if not config.dry_run:
            logger.warning("config has dry_run: false but --live was not given; output is SIMULATED")
        return SimulatedOutput()
    if config.dry_run:
        logger.error("--live requires dry_run: false in the config file; refusing to start")
        return None
    placeholders = {"", "your_username", "your_api_key", "your_share_code"}
    if {config.pishock.username, config.pishock.apikey, config.pishock.code} & placeholders:
        logger.error("PiShock credentials are not configured; run `python -m middleware.setup_wizard`")
        return None
    return PiShockOutput(config, is_stopped=estop.is_engaged)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume signed CET outbox events (JSONL) and apply PiShock policy")
    parser.add_argument("--config", default=os.getenv("MIDDLEWARE_CONFIG", "middleware/config.example.yaml"),
                        help="config YAML (default: $MIDDLEWARE_CONFIG or middleware/config.example.yaml)")
    parser.add_argument("--outbox", help="path to the emitter's outbox/events.jsonl (default: ingest.outbox_path)")
    parser.add_argument("--live", action="store_true",
                        help="enable REAL PiShock output (also requires dry_run: false in config)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive live-mode confirmation")
    parser.add_argument("--from-start", action="store_true",
                        help="process lines already in the file (stale events are still dropped)")
    parser.add_argument("--poll-interval", type=float, help="seconds between file polls")
    parser.add_argument("--duration", type=float, help="exit after N seconds (testing)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logger = _get_logger(args.verbose)
    config = load_config(args.config)
    outbox = Path(args.outbox or config.ingest.outbox_path)
    estop = EmergencyStop(config.safety.estop_file)

    if config.shared_secret == "change-me":
        logger.warning("shared_secret is the default 'change-me'; run the setup wizard to set a real one")
    if args.live and not config.dry_run and not _confirm_live(config, args.yes):
        logger.error("live mode not confirmed; exiting")
        return 2
    output = build_output(config, args.live, estop, logger)
    if output is None:
        return 2

    if estop.is_engaged():
        logger.warning("EMERGENCY STOP is engaged (%s); no output until `middleware-estop --clear`", estop.reason())
    if not outbox.parent.is_dir():
        logger.warning("outbox directory %s does not exist yet; waiting for the emitter", outbox.parent)

    logger.info("consuming %s output=%s allow_shock=%s config=%s", outbox, output.name, config.allow_shock, args.config)
    ingester = Ingester(config, output, estop=estop, logger=logger)
    try:
        run_ingest_loop(
            ingester,
            outbox,
            poll_interval_s=args.poll_interval or config.ingest.poll_interval_s,
            from_start=args.from_start,
            stop_after_s=args.duration,
        )
    except KeyboardInterrupt:
        logger.info("stopped by user")
    logger.info("summary %s", json.dumps(ingester.counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
