# Cyberpunk 2077 → PiShock (local, file-based, safety-first)

Turns Cyberpunk 2077 gameplay events into PiShock actions on your own PC.

```
Cyberpunk 2077
  └─ CET mod "pishock_emitter" (Lua)      detects damage / heal / death / combat / quests
       └─ outbox/events.jsonl             signed JSONL, one event per line
            └─ Python consumer            verify HMAC → safety checks → policy engine
                 └─ output                SIMULATED (default)  |  PiShock API (explicit opt-in)
```

The game side never touches the network: it only appends lines to a file inside
its own mod folder. Everything that decides whether something happens on your
device lives in the Python consumer.

> **Safety notice.** PiShock devices can cause injury. Read
> [Safety model](#safety-model) before enabling live output. Out of the box this
> project only **simulates** output and never contacts PiShock.

---

## What you need

- Windows PC with Cyberpunk 2077 (2.x) and [Cyber Engine Tweaks](https://www.nexusmods.com/cyberpunk2077/mods/107) installed. Launch the game once after installing CET.
- Python 3.11 or newer (from python.org).
- A PiShock account, API key and share code — only needed for live mode.

## Quick start (Windows, PowerShell)

Run these in the repository folder.

```powershell
# 1. Create a virtual environment and install
./scripts/setup_env.ps1
.\.venv\Scripts\Activate.ps1

# 2. Create your config (PiShock credentials, secret, safety limits)
#    Press Enter at the secret prompt to generate one.
python -m middleware.setup_wizard

# 3. Install the mod into the game. This also copies your secret into the mod's config.json.
python -m middleware.install_mod --config middleware/config.local.yaml
#    (add --game-dir "D:\Games\Cyberpunk 2077" if your install isn't auto-detected)

# 4. Start the consumer. Use the command printed by step 3; it looks like:
middleware-file-ingest --config middleware/config.local.yaml --outbox "C:\...\mods\pishock_emitter\outbox\events.jsonl"
```

Start the game. In the CET overlay, open **Bindings** and bind:

| Binding | What it does |
|---|---|
| **PiShock: Toggle Armed** | Shock-mapped events need the game to be *armed*. It always starts **disarmed**. |
| **PiShock: EMERGENCY STOP** | Disarms, makes the consumer latch its emergency stop, and stops emitting events. |
| **PiShock: Send Test Pulse** | Emits a `test_pulse` event, which is a beep by default. Use it to check the chain. |

The CET overlay also shows a **PiShock Emitter** window. It shows the outbox path, the last
event and whether the consumer is running or in emergency stop. It has Arm,
Test and EMERGENCY STOP buttons.

You'll see lines like this in the consumer terminal:

```
21:04:10 INFO    [SIMULATED] vibrate intensity=20 duration_ms=400 device=1 s (event=player_damaged)
```

### Try it without the game

```powershell
# terminal 1
middleware-file-ingest --outbox sim/events.jsonl
# terminal 2
middleware-simulate --outbox sim/events.jsonl --scenario demo
middleware-simulate --outbox sim/events.jsonl --scenario estop
middleware-estop --clear
```

### Linux / macOS (consumer and tests only)

```bash
./scripts/setup_env.sh && source .venv/bin/activate
python -m middleware.setup_wizard
middleware-file-ingest --config middleware/config.local.yaml --outbox /path/to/outbox/events.jsonl
```

---

## Events

| Event | How it is detected in game | Default mapping |
|---|---|---|
| `player_damaged` | Health stat pool dropped by ≥ `min_damage_pct` (1%) of max. Small hits accumulate. | `shock`, falls back to `vibrate`. Intensity = damage% × `session_max_shock_level`. |
| `player_healed` | Health rose by ≥ `heal_threshold_pct` (10%) within `heal_window_s` (3 s). Slow regeneration is ignored. | `vibrate` 10 |
| `player_death` | Health reached 0 | `beep` |
| `combat_start` / `combat_end` | `PlayerPuppet:IsInCombat()` changed | `vibrate` 6 / info only |
| `quest_completed` | `JournalNotificationQueue:OnJournalUpdate` reports a quest as Succeeded | `vibrate` 14 |
| `test_pulse` | Hotkey or overlay button | `beep` |
| `emitter_ready`, `emitter_shutdown`, `armed_changed`, `emergency_stop_cleared` | Lifecycle | info only, never output |
| `emergency_stop` | Hotkey or overlay button | latches the consumer e-stop |

Damage, heal and death come from sampling the health stat pool, not from one
damage hook. That covers every damage source: guns, melee, falls, burning and quickhacks.
It also doesn't break when a hook's signature changes in a game patch. After a load,
the emitter waits 3 s (`warmup_s`) so the health jump while loading isn't
reported. Detection thresholds can be tuned in the mod's `config.json`.

Mappings, intensities, durations and cooldowns are set in the `event_mappings`
section of your YAML config.

---

## Safety model

Output only reaches the device if **every** check below passes. Shock needs
extra checks on top.

1. **Simulated by default.** Live output needs `dry_run: false` in the config
   **and** `--live` on the command line. You then confirm by typing `LIVE`,
   or pass `--yes` for non-interactive use. If only one of the two is set, the
   consumer simulates or refuses to start. It also refuses to start with
   placeholder credentials.
2. **Shock needs three things:** `allow_shock: true` in the config, the game
   **armed** with the hotkey (which starts disarmed after every launch), and an
   event mapped to `shock`. If a mapping has a `fallback_mode`, it is used
   instead of shock until all three hold.
3. **Hard caps:** every output is clamped to `max_intensity` and
   `max_duration_ms`. Those are clamped to the device limits of 1–100 and
   ≤ 15 s, and clamped again just before the API call.
   **Durations:** the PiShock API takes whole seconds, so durations are rounded
   *down* (minimum 1 s) and every mapping under 2000 ms runs for 1 s. The
   `device=` part of each log line shows what is really sent. Set
   `subsecond_vibrate_beep: true` to send vibrate/beep of 100–1500 ms as
   milliseconds instead. That relies on an undocumented API feature which old
   PiShock Plus hubs misread (300 ms runs for 3 s), so it is off by default.
   Shock is always whole seconds.
4. **Rate limits:** per-event `cooldown_ms`, a global gap between any two
   outputs (`global_cooldown_ms`, 500 ms) and `max_actions_per_minute` (20).
5. **No replay:** the consumer only reads lines written after it started. Events
   older than `max_event_age_s` (10 s) are dropped. The emitter truncates the
   outbox every time the game starts.
6. **Integrity:** every line is HMAC-SHA256 signed with your shared secret.
   Unsigned or tampered lines are rejected. The one exception is
   `emergency_stop`, which is honored even unsigned, because stopping is always safe.
7. **Emergency stop.** Any of these engage it:
   - the in-game hotkey or overlay button
   - `middleware-estop`
   - creating the file at `safety.estop_file`
   - Ctrl+C in the consumer, which ends the process

   The consumer logs the e-stop file's full path when it starts.
   `middleware-estop` uses the same config as the consumer (see
   [Configuration reference](#configuration-reference)), so they agree on that
   file from any folder. If you start the consumer with a custom `--config`,
   pass the same `--config` to `middleware-estop`.

   While the e-stop is engaged nothing is output. The PiShock client also
   re-checks it immediately before each request. It is **only cleared
   explicitly**, with `middleware-estop --clear`. Clearing the in-game stop
   resumes event emission, but the consumer stays stopped.

---

## Configuration reference

- `middleware/config.example.yaml`: every consumer option, with comments. The wizard
  writes `middleware/config.local.yaml`, which git ignores.
- Without `--config`, every command uses `$MIDDLEWARE_CONFIG`, else
  `middleware/config.local.yaml` if it exists, else the example.
- Relative paths inside a config (`estop_file`, `outbox_path`) are relative to
  the repository root, not the folder you run the command from. Paths given on
  the command line (`--outbox`, `--estop-file`) are relative to the current folder.
- `emitter/cet/mods/pishock_emitter/config.example.json`: emitter options
  (secret, outbox path, detection thresholds, enabling each detector).
  `install_mod` writes `config.json` next to it.
  The secret must not contain `"` or `\`.

## Commands

| Command | Purpose |
|---|---|
| `middleware-file-ingest` (`python -m middleware.file_ingest`) | Consume the outbox. Flags: `--config`, `--outbox`, `--live`, `--yes`, `--from-start`, `--duration`, `--verbose` |
| `middleware-simulate` | Write signed test events: `--event TYPE [--damage N --max-health N --armed]` or `--scenario demo\|death\|estop` |
| `middleware-estop` | Engage (no args), `--clear` or `--status`. `--config` picks the config, `--estop-file` overrides the file |
| `middleware-install-mod` | Copy the mod into the game and write its `config.json` |
| `middleware-setup` | Interactive config wizard |
| `uvicorn middleware.app:app` | Older HTTP endpoint (`POST /event`), kept for compatibility. It applies the same policy, e-stop and rate limits. |

## Testing

```bash
python -m pytest -q
```

The suite runs the **real Lua emitter** (`init.lua` and `lib/`) under LuaJIT 2.1,
via [lupa](https://pypi.org/project/lupa/). That is the same Lua runtime CET uses,
with a fake CET API and CET's restricted `os`/`bit32` sandbox. The suite then feeds
the file the emitter wrote through the real consumer. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the protocol, design notes, and
what is and isn't verified against the live game.

## Troubleshooting

- **Overlay says "Consumer: not detected"**: the consumer isn't running, or
  it's reading a different outbox path. Use the path that `install_mod` printed.
- **Consumer logs `invalid_signature`**: the secret in the mod's `config.json`
  doesn't match `service.shared_secret`. Re-run `install_mod`.
- **Nothing happens on damage**: check the consumer log for `skip reason=...`.
  Common causes are `cooldown`, `global_cooldown`, `emergency_stop`, and `policy`
  (shock not permitted and no fallback mapping).
- **CET console shows `[pishock_emitter] ERROR cannot open outbox`**: the
  `outbox/` folder is missing from the installed mod. Re-run `install_mod`.
