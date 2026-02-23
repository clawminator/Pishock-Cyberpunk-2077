# Cyberpunk 2077 -> PiShock Local Middleware + File Emitter

This repository helps you connect **Cyberpunk 2077 events** to **PiShock actions** with a safety-focused local workflow.

It now includes both:
- A Python middleware/service layer (`middleware/`), and
- A CET file-based emitter scaffold (`emitter/cet/mods/pishock_emitter/`).

---

## What this project does

At a high level:
1. The in-game CET emitter writes signed event lines to a local outbox file.
2. The Python ingester reads only new lines from that file.
3. Each line signature is verified (HMAC-SHA256).
4. The policy engine decides what is allowed (cooldowns/caps/shock gate).
5. Allowed actions are sent to PiShock (or logged in dry-run mode).
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

Example: damage `100` of `400` health with `session_max_shock_level=100` -> shock intensity `25`.

---

## Before you start

You need:
- Python 3.11+
- Cyberpunk 2077 with Cyber Engine Tweaks (for emitter side)
- PiShock account
- PiShock API key + share code

---

## PiShock setup (explicit)

You will enter these values during setup:
- **PiShock username**
- **PiShock API key**
- **PiShock share code**

Where to put them:
- Run the interactive setup wizard (`python -m middleware.setup_wizard`).
- Enter the values when prompted.
- They are saved to `middleware/config.local.yaml`.

> Keep your API key private. Do not commit `middleware/config.local.yaml`.

---

## Windows quick start (non-technical, step-by-step)

> This section is written for users who just want to get running quickly.

### 1) Open PowerShell in this repo folder
- In File Explorer, open the repo folder.
- Click the address bar, type `powershell`, press Enter.

### 2) Install project dependencies
Run:

```powershell
./scripts/setup_env.ps1
```

If Python 3.11 is not picked automatically, run:

```powershell
./scripts/setup_env.ps1 -PythonBin py -PythonArgs "-3.11" -VenvDir .venv
```

### 3) Activate the Python environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4) Create your local config (PiShock credentials + safety)

```powershell
python -m middleware.setup_wizard
```

When prompted, enter:
- PiShock username
- PiShock API key
- PiShock share code
- Shared HMAC secret (choose your own secret string)
- keep defaults unless you need to change them

This creates:
- `middleware/config.local.yaml`

### 5) Point middleware to your local config

```powershell
$env:MIDDLEWARE_CONFIG = "middleware/config.local.yaml"
```

### 6) Install the CET emitter files into Cyberpunk
Copy this folder from the repo:
- `emitter/cet/mods/pishock_emitter`

Into your game directory:
- `Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/`

So final path is:
- `Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/pishock_emitter/`

Inside that folder:
- Copy `config.example.json` to `config.json`
- Set `shared_secret` in `config.json` to match the same secret from `middleware/config.local.yaml`

### 7) Start the file ingester (recommended with emitter)

```powershell
middleware-file-ingest --outbox emitter/cet/mods/pishock_emitter/outbox/events.log
```

Alternative command:

```powershell
python -m middleware.file_ingest --outbox emitter/cet/mods/pishock_emitter/outbox/events.log
```

### 8) Start the game
- Launch Cyberpunk 2077.
- Use the emitter hotkey to toggle `armed` when you intentionally want shock-capable behavior.

---

## How the emitter works (expanded)

Emitter files are in:
- `emitter/cet/mods/pishock_emitter/`

Core components:
- `init.lua`: initializes the emitter, registers CET hotkey/lifecycle hooks, writes events.
- `lib/events.lua`: event hook scaffold (you add real Observer targets here).
- `lib/outbox.lua`: writes append-only outbox lines.
- `lib/json_min.lua`: deterministic compact JSON encoder.
- `lib/crypto_hmac.lua`: computes HMAC-SHA256 signature.

### Outbox line format
Each line is:

`<hex_hmac>\t<json_body>`

Where:
- `json_body` contains `event_type`, `ts_ms`, `session_id`, `armed`, `context`, etc.
- `hex_hmac` is HMAC-SHA256 of the raw `json_body` bytes.

### Why this is useful
- No in-game HTTP dependency required for local transport.
- Python can recover from restarts by reading from saved file offsets.
- Same safety model as API path (signature verification + policy engine) is preserved.

---

## Linux / macOS quick start

```bash
./scripts/setup_env.sh
source .venv/bin/activate
python -m middleware.setup_wizard
export MIDDLEWARE_CONFIG=middleware/config.local.yaml
python -m middleware.file_ingest --outbox emitter/cet/mods/pishock_emitter/outbox/events.log
```

---

## Safety defaults

- Default behavior is conservative.
- Shock requires both:
  - `allow_shock: true` in middleware config, and
  - event `armed: true`.
- Cooldowns and max intensity/duration caps are enforced by policy.

---

## Testing

```bash
python -m pytest -q
```

---

## Additional docs

- Middleware details: `middleware/README.md`
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
