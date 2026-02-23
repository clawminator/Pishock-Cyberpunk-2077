# Cyberpunk -> PiShock Middleware (Local Service)

This repository currently provides the **local middleware service** (Python/FastAPI) that maps signed game events to PiShock actions with safety checks.

> Important: the Cyberpunk in-game emitter mod (CET/redscript side) is **not included in this repo yet**. You must provide a mod/script that POSTs events to this middleware.

## What is included
- FastAPI service with:
  - `GET /health`
  - `POST /event` (HMAC signed)
- Policy engine with:
  - event allowlist via `event_mappings`
  - cooldowns
  - max intensity / duration caps
  - shock gating (`allow_shock` + `armed`)
  - damage-based shock scaling for `player_damaged`
- PiShock legacy HTTP client (`apioperate`)
- Interactive first-run config wizard (`python -m middleware.setup_wizard`)
- Tests for signature validation, policy behavior, and event-flow simulation

## End-to-end flow (how Cyberpunk connects to PiShock)
1. **Your Cyberpunk mod emits an event** to `http://127.0.0.1:8787/event`.
2. **Middleware verifies `X-Event-Signature`** using HMAC-SHA256 over the raw request body.
3. **Policy engine resolves or rejects action** based on mapping/cooldown/caps/shock rules.
4. Middleware either:
   - returns dry-run action info (`dry_run: true`), or
   - calls PiShock `apioperate` (`shock=Op 0`, `vibrate=Op 1`, `beep=Op 2`).

## Damage percentage -> shock intensity
For `player_damaged` (when mapped to `shock`), shock intensity is computed from damage percentage:

`intensity = round((damage / max_health) * session_max_shock_level)`

Then global hard caps are applied (`max_intensity`, min 1).

Example: `damage=100`, `max_health=400`, `session_max_shock_level=100` -> `25` intensity in the PiShock API call.
FastAPI middleware that receives signed local events from Cyberpunk 2077 mods and safely maps them to PiShock actions.

## How this works (Cyberpunk -> PiShock)
This project is the **local safety bridge** between your game mod and PiShock.

1. **Cyberpunk mod emits an event**
   - Your CET/redscript side sends a JSON payload like:
     - `event_type` (e.g., `player_damaged`)
     - `ts_ms`, `session_id`, `armed`, and optional `context`
2. **Middleware verifies authenticity**
   - `POST /event` requires `X-Event-Signature` (HMAC-SHA256 over raw body).
   - If signature is invalid, request is rejected.
3. **Policy engine decides if action is allowed**
   - Looks up `event_type` in `event_mappings`.
   - Enforces cooldowns and hard caps (`max_intensity`, `max_duration_ms`).
   - Blocks `shock` unless explicitly enabled and armed.
4. **Action is sent to PiShock**
   - In `dry_run` mode (default), middleware returns what would be sent.
   - In live mode, middleware calls PiShock legacy HTTP `apioperate` with mapped action:
     - `shock` -> `Op: 0`
     - `vibrate` -> `Op: 1`
     - `beep` -> `Op: 2`

This design keeps credentials and safety rules outside the game process and prevents accidental runaway triggers.

## Safety defaults
- Binds to `127.0.0.1`
- Requires HMAC signature (`X-Event-Signature`)
- `allow_shock: false` by default
- Enforces max intensity and duration caps
- Applies cooldowns per event + target
- `dry_run: true` by default

## Approved software sources
Use official/legit package sources only:
- Python from python.org or your OS package manager
- Python packages from official PyPI: `https://pypi.org/simple`

The bootstrap scripts target official PyPI by default.
The bootstrap script targets official PyPI by default.

## Environment setup
Requirements: Python **3.11+**.

### Linux / macOS

From repo root:

```bash
# If python3 already points to 3.11+
./scripts/setup_env.sh

# Or explicitly choose interpreter
PYTHON_BIN=python3.11 ./scripts/setup_env.sh

source .venv/bin/activate
```

### Windows (PowerShell)

```powershell
# If py launcher resolves to 3.11+
./scripts/setup_env.ps1

# Or explicitly choose interpreter and venv directory
./scripts/setup_env.ps1 -PythonBin py -PythonArgs "-3.11" -VenvDir .venv

.\.venv\Scripts\Activate.ps1
```

## First run (interactive config)
```bash
python -m middleware.setup_wizard
```

Wizard prompts include **Session max shock level (1-100)**. This value is used in the damage percentage formula above.
These scripts create `.venv`, install runtime + test dependencies from official PyPI, and run import checks.

## First run (interactive config)
Use official package sources only:
- Python from python.org / system package manager
- Python packages from official PyPI: `https://pypi.org/simple`

The bootstrap script enforces official PyPI by default.

## Environment setup (recommended)
From repo root:

```bash
./scripts/setup_env.sh
source .venv/bin/activate
```

What this does:
- creates `.venv`
- ensures pip is available in the venv
- installs project + test dependencies using `--no-build-isolation`
- verifies required modules are importable

## First run (interactive)
Use the setup wizard to collect your local credentials/config values:

```bash
python -m middleware.setup_wizard
```

This writes `middleware/config.local.yaml`.

Run service:
Then run with:

```bash
export MIDDLEWARE_CONFIG=middleware/config.local.yaml
uvicorn middleware.app:app --host 127.0.0.1 --port 8787
```

## Event payload expected by `/event`
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

## Simulated request
  "armed": false,
  "context": {"source": "cet"}
}
```

## Generate `X-Event-Signature`
## Generate signature
```python
import hashlib, hmac, json
secret = "change-me"
body = json.dumps({
    "event_type": "player_damaged",
    "ts_ms": 1700000000000,
    "session_id": "session-1",
    "armed": False,
    "context": {"source": "cet"}
}, separators=(",", ":")).encode("utf-8")
sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
print(sig)
```

## Simulated request
Then include the value as `X-Event-Signature` in `POST /event`.

## Simulated event test request
```bash
curl -i -X POST http://127.0.0.1:8787/event \
  -H "content-type: application/json" \
  -H "X-Event-Signature: <computed_hex_hmac>" \
  --data '{"event_type":"player_damaged","ts_ms":1700000000000,"session_id":"session-1","armed":true,"context":{"source":"cet","damage":100,"max_health":400}}'
```

Expected in dry-run mode: HTTP `202` and an action containing `"mode":"shock"` and `"intensity":25` for that example.
  --data '{"event_type":"player_damaged","ts_ms":1700000000000,"session_id":"session-1","armed":false,"context":{"source":"cet"}}'
```

Expected in dry-run mode: HTTP `202` and `{"accepted":true,"dry_run":true,...}`.

## Default event behavior
- `player_damaged` -> `shock` (only event mapped to shock by default; still requires `allow_shock: true` and `armed: true`).
- Positive events such as `player_healed` and `quest_completed` -> `vibrate`.

## Tests
- Additional events should follow the same pattern unless you intentionally override in config.

## Tests
Expected (dry-run mode): HTTP `202` with `{"accepted":true,"dry_run":true,...}`.

## Run tests
```bash
python -m pytest -q
```
