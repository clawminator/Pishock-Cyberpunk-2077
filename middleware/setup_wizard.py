"""Interactive first-run setup wizard for middleware config generation.

Run this once to create a local YAML config with your PiShock credentials and
safety defaults before launching the service.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from .config import DEFAULT_OUTBOX_PATH

# Safety-oriented starter profile:
# - damage events are the only shock mapping, and fall back to vibrate while
#   shock is disabled or the game is not armed
# - positive events default to vibrate
# - damage->shock intensity is computed dynamically from damage percent
DEFAULT_EVENT_MAPPINGS = {
    "player_damaged": {"mode": "shock", "fallback_mode": "vibrate", "intensity": 8, "duration_ms": 400, "cooldown_ms": 2000},
    "player_healed": {"mode": "vibrate", "intensity": 10, "duration_ms": 500, "cooldown_ms": 1500},
    "player_death": {"mode": "beep", "intensity": 1, "duration_ms": 1000, "cooldown_ms": 5000},
    "combat_start": {"mode": "vibrate", "intensity": 6, "duration_ms": 300, "cooldown_ms": 5000},
    "quest_completed": {"mode": "vibrate", "intensity": 14, "duration_ms": 700, "cooldown_ms": 4000},
    "test_pulse": {"mode": "beep", "intensity": 1, "duration_ms": 300, "cooldown_ms": 1000},
}


def _ask(prompt: str, default: str | None = None) -> str:
    """Prompt helper that supports default values."""

    label = f"{prompt}"
    if default is not None:
        label += f" [{default}]"
    label += ": "
    value = input(label).strip()
    if not value and default is not None:
        return default
    return value


def _ask_bool(prompt: str, default: bool) -> bool:
    return _ask(f"{prompt} (true/false)", "true" if default else "false").lower() in ("true", "yes", "y", "1")


def _q(value: object) -> str:
    """Quote a scalar for YAML. JSON strings are valid YAML scalars."""

    return json.dumps(str(value))


def _emit_yaml(config: dict) -> str:
    """Render a small deterministic YAML document without external deps."""

    service = config["service"]
    safety = config["safety"]
    ingest = config["ingest"]
    pishock = config["pishock"]
    event_mappings = config["event_mappings"]

    lines = [
        "service:",
        f"  bind_host: {_q(service['bind_host'])}",
        f"  bind_port: {service['bind_port']}",
        f"  shared_secret: {_q(service['shared_secret'])}",
        f"  dry_run: {str(service['dry_run']).lower()}",
        f"  allow_shock: {str(service['allow_shock']).lower()}",
        f"  max_intensity: {service['max_intensity']}",
        f"  max_duration_ms: {service['max_duration_ms']}",
        f"  default_cooldown_ms: {service['default_cooldown_ms']}",
        f"  session_max_shock_level: {service['session_max_shock_level']}",
        "",
        "safety:",
        f"  max_actions_per_minute: {safety['max_actions_per_minute']}",
        f"  global_cooldown_ms: {safety['global_cooldown_ms']}",
        f"  max_event_age_s: {safety['max_event_age_s']}",
        f"  estop_file: {_q(safety['estop_file'])}",
        "",
        "ingest:",
        f"  outbox_path: {_q(ingest['outbox_path'])}",
        f"  poll_interval_s: {ingest['poll_interval_s']}",
        "",
        "pishock:",
        f"  username: {_q(pishock['username'])}",
        f"  apikey: {_q(pishock['apikey'])}",
        f"  code: {_q(pishock['code'])}",
        f"  name: {_q(pishock['name'])}",
        "",
        "event_mappings:",
    ]

    for event_name, mapping in event_mappings.items():
        lines.append(f"  {event_name}:")
        lines.append(f"    mode: {mapping['mode']}")
        if "fallback_mode" in mapping:
            lines.append(f"    fallback_mode: {mapping['fallback_mode']}")
        lines.extend(
            [
                f"    intensity: {mapping['intensity']}",
                f"    duration_ms: {mapping['duration_ms']}",
                f"    cooldown_ms: {mapping['cooldown_ms']}",
            ]
        )

    return "\n".join(lines) + "\n"


def run_wizard(output_path: str = "middleware/config.local.yaml") -> Path:
    """Prompt for required values and write config to disk."""

    print("Cyberpunk PiShock Middleware - First Run Setup")
    print("This writes a local config file with conservative safety defaults.\n")

    username = _ask("PiShock username")
    apikey = _ask("PiShock API key")
    code = _ask("PiShock share code")
    shared_secret = _ask("Shared HMAC secret for game->middleware events (Enter = generate)", "")
    if not shared_secret:
        shared_secret = secrets.token_hex(16)
        print(f"  generated secret: {shared_secret}")
    while '"' in shared_secret or "\\" in shared_secret:
        shared_secret = _ask("Secret must not contain quotes or backslashes; enter another")

    outbox_path = _ask("Emitter outbox file (set by middleware.install_mod)", DEFAULT_OUTBOX_PATH)
    bind_host = _ask("Bind host (HTTP mode only)", "127.0.0.1")
    bind_port = int(_ask("Bind port (HTTP mode only)", "8787"))
    dry_run = _ask_bool("Enable dry_run (simulated output only)?", True)
    allow_shock = _ask_bool("Allow shock mode?", False)
    session_max_shock_level = int(_ask("Session max shock level (1-100)", "100"))
    max_intensity = int(_ask("Hard max intensity for any output (1-100)", "20"))

    config = {
        "service": {
            "bind_host": bind_host,
            "bind_port": bind_port,
            "shared_secret": shared_secret,
            "dry_run": dry_run,
            # Needed so player_damaged -> shock mapping can operate when armed.
            "allow_shock": allow_shock,
            "max_intensity": min(max(1, max_intensity), 100),
            "max_duration_ms": 2000,
            "default_cooldown_ms": 1500,
            "session_max_shock_level": min(max(1, session_max_shock_level), 100),
        },
        "safety": {
            "max_actions_per_minute": 20,
            "global_cooldown_ms": 500,
            "max_event_age_s": 10,
            "estop_file": "middleware/state/ESTOP",
        },
        "ingest": {"outbox_path": outbox_path, "poll_interval_s": 0.1},
        "pishock": {
            "username": username,
            "apikey": apikey,
            "code": code,
            "name": "CyberpunkBridge",
        },
        "event_mappings": DEFAULT_EVENT_MAPPINGS,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_emit_yaml(config), encoding="utf-8")

    print(f"\nConfig written: {out}")
    print("Next: install the emitter into the game with")
    print(f"  python -m middleware.install_mod --config {out}")
    return out


if __name__ == "__main__":
    run_wizard()
