# Architecture

## Data flow

```
CET (LuaJIT, sandboxed)                       Python consumer
─────────────────────────                     ──────────────────────────────────────────
init.lua        lifecycle, hotkeys, overlay   file_ingest.OutboxTailer  complete lines only,
lib/events.lua  detectors (health sampling,                             handles truncation
                combat poll, journal observer) file_ingest.Ingester      parse → e-stop event?
lib/game_api.lua pcall-guarded game calls                               → HMAC → info? → stale?
lib/outbox.lua  JSONL writer  ──────────────▶                           → e-stop? → policy
lib/crypto_hmac.lua HMAC-SHA256                                         → rate limit → output
lib/json_min.lua deterministic JSON           output.SimulatedOutput | output.PiShockOutput
lib/status.lua  reads consumer_status.txt ◀── file_ingest.write_status (every 1 s)
```

## Outbox protocol (v1)

File: `<mod>/outbox/events.jsonl`. It's truncated when the emitter starts and
when it passes `max_outbox_bytes`. Each line is one JSON object, always written in
this exact key order:

```json
{"v":1,"sig":"<64 lowercase hex>","event":{"armed":false,"context":{...},"event_type":"player_damaged","seq":7,"session_id":"cp77-1791939513","ts_ms":1791939520000}}
```

- `sig` = HMAC-SHA256(shared_secret, exact bytes of the `event` object as written).
  The consumer extracts those bytes with a regex (`middleware/protocol.py`) and
  never re-serializes, so float formatting can't break signatures.
- `event` keys are sorted and there's no whitespace. `ts_ms` is wall-clock
  (`os.time()*1000`, second resolution: CET has no millisecond wall clock).
- The legacy format `<hex>\t<json>` is still accepted.

`consumer_status.txt` (written by the consumer, read by the overlay) holds
`key=value` lines: `ts`, `state` (running/stopped), `output` (simulated/live),
`estop` (0/1), `sent`, `last`.

## Why file-based (and what Convai showed)

The Convai Cyberpunk mod (`Conv-AI/Convai-Modding`, branch `Cyberpunk-2077`) is a
working example of the same constraint. Their docs state *"Cyber Engine Tweaks
does not support os.execute"*. Their Lua mod and `main.exe` communicate only
through text files in a folder shipped inside the mod (`convai/control.txt`,
`response.txt`, ...), and the user starts the external process manually.
Patterns we adopted:

- An IPC directory that ships with the mod (`outbox/`): CET can't create directories.
- An external process started by the user. The game never launches anything.
- A reverse channel the mod polls, which for us is `consumer_status.txt`. It gives
  in-game feedback that the consumer is alive.
- Hotkeys plus an ImGui overlay for control.

Patterns we deliberately did *not* adopt: single-slot control files that get
overwritten (we use an append-only log with offsets, so no event is lost to
a race), and polling with 1 s granularity.

## CET sandbox facts the emitter depends on

Checked against CET source (`src/scripting/LuaSandbox.cpp`, `Scripting.cpp`) and sol2:

- `os` only exposes `clock`, `date`, `difftime` and `time`, plus wrapped `rename` and
  `remove`. There's **no `os.execute`**. The previous scaffold called it to
  create the outbox dir, which would have errored in game.
- `io.open` is limited to the mod directory, and there's no mkdir.
- `bit32` is exposed, but under LuaJIT sol2 binds it to **LuaJIT's `bit` library**
  (`luaL_requiref(L, "bit32", luaopen_bit, 1)`). It has signed results, shift
  counts are taken mod 32, and it offers `ror` rather than `rrotate`. The previous
  SHA-256 encoded the message length with `rshift(len, 32..56)`, which under
  LuaJIT equals `rshift(len, 0..24)`. **Every signature it produced was wrong.**
  This is fixed and covered by tests that run under LuaJIT.

## Game APIs used

All are pcall-guarded, and each one is used by several published CET mods:

| API | Used for | Seen in |
|---|---|---|
| `Game.GetStatPoolsSystem():GetStatPoolValue(id, gamedataStatPoolType.Health, false)` | current HP | CP77-DiscordRPC2, QuestRunner, cyberpunk-vr-port |
| `Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Health)` | max HP | same |
| `PlayerPuppet:IsInCombat()` | combat state | several mods (Drone Companions, others) |
| `Observe("JournalNotificationQueue", "OnJournalUpdate", fn(_, hash, className))` + `Game.GetJournalManager():GetEntry/GetEntryState`, `gameJournalEntryState.Succeeded` | quest completion | CP77 Stock Market |
| `PlayerPuppet:SetWarningMessage(text)` | on-screen notice | DualSense Support, MetroSystem |

## What is verified, and what isn't

Verified by the automated suite (`python -m pytest`):
- The Lua emitter runs under LuaJIT 2.1 with CET's restricted `os` and `bit32`. Its
  signatures match Python for edge-case lengths, UTF-8 and long keys. The tests cover
  detector behavior (warm-up, accumulation, regen filter, death/revive,
  combat, quest dedupe), hotkeys, overlay, e-stop, outbox fallback and the size cap.
- Emitter file → consumer → simulated output end to end, including the
  in-game e-stop latching the consumer and blocking a (mocked) live sender.
- Consumer CLI behavior: refusing live mode without confirmation or with a dry-run
  config, the simulator, the e-stop CLI, the wizard and the installer.

Not verified here, because it needs the real game or device:
- Running inside an actual Cyberpunk 2077 + CET install. The API calls above are
  taken from working mods, but game patches can change them. The detectors fail
  safe: if a call breaks, nothing is emitted.
- Real PiShock requests. The client is tested against mocked HTTP responses
  taken from the PiShock API docs (`"Operation Succeeded."`, `"Not Authorized."`, ...).
