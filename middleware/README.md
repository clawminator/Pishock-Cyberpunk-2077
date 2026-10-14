# middleware (Python)

The Python side of the bridge. For setup and usage, see the [top-level README](../README.md).
For the protocol and design notes, see [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

| Module | Role |
|---|---|
| `file_ingest.py` | **Main entry point.** Tails the emitter's JSONL outbox, runs each line through verify, safety, policy and output, and writes `consumer_status.txt` |
| `protocol.py` | Outbox line format: `build_line` / `parse_line` / `sign` |
| `policy.py` | Event → action mapping, shock gating plus `fallback_mode`, damage scaling, caps, per-event cooldowns |
| `safety.py` | `EmergencyStop` (file latch), `RateLimiter`, and the `middleware-estop` CLI |
| `output.py` | `SimulatedOutput` (default) and `PiShockOutput` (live only) |
| `pishock_http.py` | PiShock `apioperate` client, which clamps to device limits and checks the response body |
| `config.py` | YAML loading, validation and clamping |
| `simulate.py` | `middleware-simulate`: writes signed events without the game |
| `install_mod.py` | Copies the CET mod into the game and writes its `config.json` |
| `setup_wizard.py` | Interactive config generator |
| `app.py` | Older FastAPI `POST /event` endpoint, using the same policy, e-stop and rate limits |

Damage scaling: for `player_damaged`, intensity is
`round(damage / max_health * session_max_shock_level)`, which is then capped by `max_intensity`.
For example, 100 damage of 400 max health with level 100 gives intensity 25.
