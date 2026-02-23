# Cyberpunk 2077 -> PiShock Local Middleware

This repository contains a **local middleware service** that receives signed game events and safely maps them to PiShock actions.

- The middleware is written in Python/FastAPI.
- It supports Windows and Linux setup scripts.
- It includes an interactive first-run wizard for credentials + safety settings.

> This repo does **not** include the in-game Cyberpunk event emitter yet. You must use your own CET/redscript mod (or equivalent) to send events to this middleware.

---

## What this does (high-level)

1. Your game-side mod sends event JSON to `POST /event` on your local machine.
2. Middleware verifies request signature (`X-Event-Signature`, HMAC-SHA256).
3. Middleware applies safety policy (allowlist, cooldowns, max caps, shock gating).
4. Middleware calls PiShock legacy API (`apioperate`) when allowed.

For damage events (`player_damaged`), shock intensity is scaled by damage percent:

`intensity = round((damage / max_health) * session_max_shock_level)`

Example: damage `100` of max health `400` with `session_max_shock_level=100` -> intensity `25`.

---

## Prerequisites

- Python 3.11+
- A PiShock account
- A PiShock API key and share code

---

## Where to get your PiShock API details (important)

You will need these values for setup:

- **PiShock username**
- **PiShock API key**
- **PiShock share code** (for the target shocker)

### How to add your PiShock API info to this project

Use the interactive setup wizard and enter your values when prompted:

- `PiShock username`
- `PiShock API key`
- `PiShock share code`
- `Shared HMAC secret for game->middleware events`

The wizard writes these into `middleware/config.local.yaml`.

> Treat your API key like a password. Do not commit `middleware/config.local.yaml` to git.

---

## Quick start (Windows first)

### Windows (PowerShell) — recommended

```powershell
# 1) Create venv + install deps from official PyPI
./scripts/setup_env.ps1

# If needed, force Python 3.11 explicitly:
./scripts/setup_env.ps1 -PythonBin py -PythonArgs "-3.11" -VenvDir .venv

# 2) Activate environment
.\.venv\Scripts\Activate.ps1

# 3) Run first-time interactive setup
python -m middleware.setup_wizard

# 4) Point service to your local config
$env:MIDDLEWARE_CONFIG = "middleware/config.local.yaml"

# 5) Start middleware
uvicorn middleware.app:app --host 127.0.0.1 --port 8787
```

### Linux / macOS

```bash
# 1) Create venv + install deps from official PyPI
./scripts/setup_env.sh

# If needed, force Python 3.11 explicitly:
PYTHON_BIN=python3.11 ./scripts/setup_env.sh

# 2) Activate environment
source .venv/bin/activate

# 3) Run first-time interactive setup
python -m middleware.setup_wizard

# 4) Point service to your local config
export MIDDLEWARE_CONFIG=middleware/config.local.yaml

# 5) Start middleware
uvicorn middleware.app:app --host 127.0.0.1 --port 8787
```

---

## Interactive setup wizard

Run:

```bash
python -m middleware.setup_wizard
```

You will be prompted for:

- PiShock username
- PiShock API key
- PiShock share code
- Shared HMAC secret
- bind host/port
- dry run toggle
- shock enable toggle
- session max shock level (1-100)

The wizard writes `middleware/config.local.yaml`.

---

## Common usage notes

- By default, only `player_damaged` is mapped to `shock`.
- Positive events default to `vibrate`.
- Shock still requires both:
  - `allow_shock: true` in config, and
  - `armed: true` in incoming event payload.

---

## Example event payload

```json
{
  "event_type": "player_damaged",
  "ts_ms": 1700000000000,
  "session_id": "session-1",
  "armed": true,
  "context": {
    "source": "cet",
    "damage": 100,
    "max_health": 400
  }
}
```

---

## Testing

```bash
python -m pytest -q
```

---

## More detailed docs

See middleware-specific details in:

- `middleware/README.md`

---

## File-based CET emitter (new)

This repo now includes a **file-based emitter scaffold** under:

- `emitter/cet/mods/pishock_emitter/`

It writes signed outbox lines in this format:

`<hex_hmac>\t<json_body>`

### CET install path

Copy the `pishock_emitter` folder to your Cyberpunk CET mods directory:

- `Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/pishock_emitter/`

Then copy:

- `config.example.json` -> `config.json`

and set `shared_secret` to match your middleware config secret.

### Python ingester for file outbox

Run the ingester (instead of HTTP `/event`) to consume the outbox file:

```bash
middleware-file-ingest --outbox emitter/cet/mods/pishock_emitter/outbox/events.log
```

or:

```bash
python -m middleware.file_ingest --outbox emitter/cet/mods/pishock_emitter/outbox/events.log
```

The ingester reuses the same safety policy and PiShock client modules as the HTTP path.
