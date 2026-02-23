# Cyberpunk -> PiShock Middleware (Local Service)

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

Then run with:

```bash
export MIDDLEWARE_CONFIG=middleware/config.local.yaml
uvicorn middleware.app:app --host 127.0.0.1 --port 8787
```

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

Then include the value as `X-Event-Signature` in `POST /event`.

## Simulated event test request
```bash
curl -i -X POST http://127.0.0.1:8787/event \
  -H "content-type: application/json" \
  -H "X-Event-Signature: <computed_hex_hmac>" \
  --data '{"event_type":"player_damaged","ts_ms":1700000000000,"session_id":"session-1","armed":false,"context":{"source":"cet"}}'
```

Expected (dry-run mode): HTTP `202` with `{"accepted":true,"dry_run":true,...}`.

## Run tests
```bash
python -m pytest -q
```
