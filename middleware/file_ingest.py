"""File-based event ingester for CET outbox lines.

Reads lines in the format: <sig_hex>\t<json_body>\n
The ingester reuses middleware security/policy/PiShock modules so behavior matches
POST /event processing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from .config import load_config
from .policy import CooldownError, PolicyEngine, PolicyError
from .security import verify_signature


def _load_offset(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return 0


def _save_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


def _process_line(line: str, policy: PolicyEngine, config, logger: logging.Logger) -> bool:
    line = line.rstrip("\n")
    if not line:
        return False

    try:
        sig_hex, json_body = line.split("\t", 1)
    except ValueError:
        logger.warning("ingest_skip malformed_line")
        return False

    body_bytes = json_body.encode("utf-8")
    if not verify_signature(body_bytes, sig_hex, config.shared_secret):
        logger.warning("ingest_skip invalid_signature")
        return False

    try:
        event = json.loads(json_body)
        action = policy.decide(event)
    except json.JSONDecodeError:
        logger.warning("ingest_skip invalid_json")
        return False
    except CooldownError as exc:
        logger.warning("ingest_skip cooldown detail=%s", str(exc))
        return False
    except (PolicyError, KeyError, TypeError, ValueError) as exc:
        logger.warning("ingest_skip policy_error detail=%s", str(exc))
        return False

    if config.dry_run:
        logger.info(
            "ingest_dry_run event_type=%s mode=%s intensity=%s duration_ms=%s",
            event.get("event_type"),
            action.mode,
            action.intensity,
            action.duration_ms,
        )
        return True

    from .pishock_http import send_pishock_http

    result = send_pishock_http(
        mode=action.mode,
        intensity=action.intensity,
        duration_ms=action.duration_ms,
        username=config.pishock.username,
        apikey=config.pishock.apikey,
        code=action.target,
        name=config.pishock.name,
    )
    if not result.ok:
        logger.warning("ingest_pishock_failed status=%s body=%s", result.status_code, result.body)
        return False

    logger.info("ingest_sent event_type=%s mode=%s intensity=%s", event.get("event_type"), action.mode, action.intensity)
    return True


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("middleware.file_ingest")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())
    return logger


def run_ingest_loop(outbox: Path, offset_file: Path, poll_interval_s: float = 0.25) -> None:
    logger = _get_logger()
    cfg_path = os.getenv("MIDDLEWARE_CONFIG", "middleware/config.example.yaml")
    config = load_config(cfg_path)
    policy = PolicyEngine(config)

    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.touch(exist_ok=True)

    offset = _load_offset(offset_file)

    while True:
        with outbox.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                _process_line(line, policy, config, logger)
                offset = handle.tell()
                _save_offset(offset_file, offset)

        time.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest signed CET outbox events from a local file")
    parser.add_argument(
        "--outbox",
        default="emitter/cet/mods/pishock_emitter/outbox/events.log",
        help="Path to emitter outbox log file",
    )
    parser.add_argument(
        "--offset-file",
        default="middleware/state/outbox.offset",
        help="Path to file offset state",
    )
    parser.add_argument("--poll-interval", type=float, default=0.25)
    args = parser.parse_args()

    run_ingest_loop(Path(args.outbox), Path(args.offset_file), args.poll_interval)


if __name__ == "__main__":
    main()
