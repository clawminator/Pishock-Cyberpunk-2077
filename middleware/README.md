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

This writes `middleware/config.local.yaml`.

Run service:

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
```bash
curl -i -X POST http://127.0.0.1:8787/event \
  -H "content-type: application/json" \
  -H "X-Event-Signature: <computed_hex_hmac>" \
  --data '{"event_type":"player_damaged","ts_ms":1700000000000,"session_id":"session-1","armed":true,"context":{"source":"cet","damage":100,"max_health":400}}'
```

Expected in dry-run mode: HTTP `202` and an action containing `"mode":"shock"` and `"intensity":25` for that example.

## Default event behavior
- `player_damaged` -> `shock` (only event mapped to shock by default; still requires `allow_shock: true` and `armed: true`).
- Positive events such as `player_healed` and `quest_completed` -> `vibrate`.

## Tests
```bash
python -m pytest -q
```
