"""Write signed events into an outbox file without running the game.

Useful for testing the consumer end to end:

    # terminal 1
    middleware-file-ingest --outbox sim/events.jsonl
    # terminal 2
    middleware-simulate --outbox sim/events.jsonl --scenario demo
    middleware-simulate --outbox sim/events.jsonl --event player_damaged --damage 100 --max-health 400 --armed
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from .config import default_config_path
from .protocol import build_line

SCENARIOS: dict[str, list[tuple[float, str, dict[str, Any]]]] = {
    # (delay before event in seconds, event_type, context)
    "demo": [
        (0.0, "emitter_ready", {"source": "simulator"}),
        (0.5, "test_pulse", {"source": "simulator"}),
        (2.0, "combat_start", {"source": "simulator"}),
        (1.0, "player_damaged", {"source": "simulator", "damage": 40, "max_health": 400, "health": 360}),
        (2.5, "player_damaged", {"source": "simulator", "damage": 100, "max_health": 400, "health": 260}),
        (2.5, "player_healed", {"source": "simulator", "amount": 120, "max_health": 400, "health": 380}),
        (2.0, "combat_end", {"source": "simulator"}),
        (1.0, "quest_completed", {"source": "simulator", "quest_id": "sim_quest", "title": "Simulated Gig"}),
    ],
    "death": [
        (0.0, "player_damaged", {"source": "simulator", "damage": 400, "max_health": 400, "health": 0}),
        (0.1, "player_death", {"source": "simulator", "max_health": 400}),
    ],
    "estop": [
        (0.0, "test_pulse", {"source": "simulator"}),
        (1.0, "emergency_stop", {"source": "simulator"}),
        (1.0, "test_pulse", {"source": "simulator"}),
    ],
}


class Simulator:
    def __init__(self, outbox: Path, secret: str, armed: bool = False, session_id: str = "sim") -> None:
        self.outbox = outbox
        self.secret = secret
        self.armed = armed
        self.session_id = f"{session_id}-{int(time.time())}"
        self.seq = 0

    def emit(self, event_type: str, context: dict[str, Any] | None = None) -> str:
        self.seq += 1
        event = {
            "event_type": event_type,
            "ts_ms": int(time.time()) * 1000,
            "session_id": self.session_id,
            "armed": self.armed,
            "seq": self.seq,
            "context": context or {},
        }
        line = build_line(event, self.secret)
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
        return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append simulated signed game events to an outbox file")
    parser.add_argument("--config", default=default_config_path())
    parser.add_argument("--outbox", help="outbox file (default: ingest.outbox_path from config)")
    parser.add_argument("--secret", help="HMAC secret (default: service.shared_secret from config)")
    parser.add_argument("--armed", action="store_true", help="mark events as armed (needed for shock mappings)")
    parser.add_argument("--speed", type=float, default=1.0, help="scenario time multiplier (2 = twice as fast)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event", help="single event_type to emit")
    group.add_argument("--scenario", choices=sorted(SCENARIOS), help="emit a scripted sequence")
    parser.add_argument("--damage", type=float)
    parser.add_argument("--max-health", type=float)
    args = parser.parse_args(argv)

    secret, outbox = args.secret, args.outbox
    if secret is None or outbox is None:
        from .config import load_config  # pylint: disable=import-outside-toplevel

        cfg = load_config(args.config)
        secret = secret or cfg.shared_secret
        outbox = outbox or cfg.ingest.outbox_path

    sim = Simulator(Path(outbox), secret, armed=args.armed)
    if args.event:
        context: dict[str, Any] = {"source": "simulator"}
        if args.damage is not None:
            context["damage"] = args.damage
        if args.max_health is not None:
            context["max_health"] = args.max_health
        sim.emit(args.event, context)
        print(f"wrote {args.event} -> {outbox}")
        return 0

    for delay, event_type, context in SCENARIOS[args.scenario]:
        time.sleep(delay / max(args.speed, 0.01))
        sim.emit(event_type, context)
        print(f"wrote {event_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
