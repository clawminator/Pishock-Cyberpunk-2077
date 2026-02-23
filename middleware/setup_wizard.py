"""Interactive first-run setup wizard for middleware config generation.

Run this once to create a local YAML config with your PiShock credentials and
safety defaults before launching the service.
"""

from __future__ import annotations

from pathlib import Path


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


def _emit_yaml(config: dict) -> str:
    """Render a small deterministic YAML document without external deps."""

    service = config["service"]
    pishock = config["pishock"]
    event_mappings = config["event_mappings"]

    lines = [
        "service:",
        f"  bind_host: {service['bind_host']}",
        f"  bind_port: {service['bind_port']}",
        f"  shared_secret: {service['shared_secret']}",
        f"  dry_run: {str(service['dry_run']).lower()}",
        f"  allow_shock: {str(service['allow_shock']).lower()}",
        f"  max_intensity: {service['max_intensity']}",
        f"  max_duration_ms: {service['max_duration_ms']}",
        f"  default_cooldown_ms: {service['default_cooldown_ms']}",
        f"  session_max_shock_level: {service['session_max_shock_level']}",
        "",
        "pishock:",
        f"  username: {pishock['username']}",
        f"  apikey: {pishock['apikey']}",
        f"  code: {pishock['code']}",
        f"  name: {pishock['name']}",
        "",
        "event_mappings:",
    ]

    for event_name, mapping in event_mappings.items():
        lines.extend(
            [
                f"  {event_name}:",
                f"    mode: {mapping['mode']}",
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
    shared_secret = _ask("Shared HMAC secret for game->middleware events")

    bind_host = _ask("Bind host", "127.0.0.1")
    bind_port = int(_ask("Bind port", "8787"))
    dry_run = _ask("Enable dry_run? (true/false)", "true").lower() == "true"
    allow_shock = _ask("Allow shock mode? (true/false)", "false").lower() == "true"
    session_max_shock_level = int(
        _ask("Session max shock level (1-100)", "100")
    )

    # Safety-oriented starter profile:
    # - damage events are the only shock mapping
    # - positive events default to vibrate
    # - damage->shock intensity is computed dynamically from damage percent
    config = {
        "service": {
            "bind_host": bind_host,
            "bind_port": bind_port,
            "shared_secret": shared_secret,
            "dry_run": dry_run,
            "allow_shock": allow_shock,
            "max_intensity": 20,
            "max_duration_ms": 2000,
            "default_cooldown_ms": 1500,
            "session_max_shock_level": min(max(1, session_max_shock_level), 100),
        },
        "pishock": {
            "username": username,
            "apikey": apikey,
            "code": code,
            "name": "CyberpunkBridge",
        },
        "event_mappings": {
            "player_damaged": {"mode": "shock", "intensity": 8, "duration_ms": 400, "cooldown_ms": 2000},
            "player_healed": {"mode": "vibrate", "intensity": 10, "duration_ms": 500, "cooldown_ms": 1500},
            "quest_completed": {"mode": "vibrate", "intensity": 14, "duration_ms": 700, "cooldown_ms": 4000},
        },
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_emit_yaml(config), encoding="utf-8")

    print(f"\nConfig written: {out}")
    print("Set MIDDLEWARE_CONFIG to this path before running uvicorn.")
    return out


if __name__ == "__main__":
    run_wizard()
