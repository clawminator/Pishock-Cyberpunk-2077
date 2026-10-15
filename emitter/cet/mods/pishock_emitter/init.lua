-- PiShock Emitter for Cyber Engine Tweaks.
--
-- Detects game events and appends signed JSONL lines to outbox/events.jsonl.
-- It never talks to the network or to PiShock: the Python consumer
-- (middleware.file_ingest) reads the file and applies all safety policy.
--
-- Safety controls in game (bind them in CET > Bindings):
--   * Toggle Armed      - shock-mapped events require armed=true (starts DISARMED)
--   * EMERGENCY STOP    - disarms, tells the consumer to latch its e-stop,
--                         and suppresses further events until cleared in the overlay
--   * Send Test Pulse   - emits a test_pulse event (beep in the default mapping)

local Config = require("lib/config")
local Outbox = require("lib/outbox")
local Events = require("lib/events")
local GameApi = require("lib/game_api")
local Status = require("lib/status")

local VERSION = "1.0.0"
local TAG = "[pishock_emitter]"

-- Events that are still written while the in-game e-stop is engaged.
local ESTOP_PASSTHROUGH = {
  emergency_stop = true,
  emergency_stop_cleared = true,
  emitter_shutdown = true,
}

local emitter = {
  cfg = nil,
  config_source = nil,
  armed = false,
  estop = false,
  session_id = nil,
  seq = 0,
  outbox = nil,
  outbox_error = nil,
  events = nil,
  observers_ok = false,
  last_event = "-",
  overlay_open = false,
  status = nil,
  status_timer = 0,
}

local function log(fmt, ...)
  print(TAG .. " " .. string.format(fmt, ...))
end

local function emit(event_type, context)
  if not emitter.outbox then
    return false
  end
  if emitter.estop and not ESTOP_PASSTHROUGH[event_type] then
    return false
  end
  emitter.seq = emitter.seq + 1
  local ok = emitter.outbox:emit({
    event_type = event_type,
    ts_ms = os.time() * 1000,
    session_id = emitter.session_id,
    armed = emitter.armed,
    seq = emitter.seq,
    context = context or {},
  })
  if ok then
    emitter.last_event = event_type
  end
  return ok
end

local function set_armed(value)
  if emitter.estop and value then
    log("cannot arm while emergency stop is engaged")
    GameApi.notify("PiShock: clear E-STOP before arming")
    return
  end
  emitter.armed = value
  emit("armed_changed", { armed = value })
  log("armed=%s", tostring(value))
  GameApi.notify(value and "PiShock: ARMED" or "PiShock: disarmed")
end

local function emergency_stop()
  emitter.armed = false
  emitter.estop = true
  emit("emergency_stop", { source = "hotkey" })
  log("EMERGENCY STOP engaged")
  GameApi.notify("PiShock: EMERGENCY STOP")
end

local function clear_emergency_stop()
  if not emitter.estop then
    return
  end
  emitter.estop = false
  emit("emergency_stop_cleared", { source = "overlay" })
  log("in-game emergency stop cleared (the consumer's e-stop must be cleared separately)")
end

registerHotkey("pishock_toggle_armed", "PiShock: Toggle Armed", function()
  set_armed(not emitter.armed)
end)

registerHotkey("pishock_emergency_stop", "PiShock: EMERGENCY STOP", function()
  emergency_stop()
end)

registerHotkey("pishock_test_pulse", "PiShock: Send Test Pulse", function()
  emit("test_pulse", { source = "hotkey" })
end)

registerForEvent("onInit", function()
  emitter.cfg, emitter.config_source = Config.load({ "config.json", "config.example.json" })
  emitter.session_id = string.format("%s-%d", emitter.cfg.session_id_prefix, os.time())

  emitter.outbox, emitter.outbox_error = Outbox.new({
    path = emitter.cfg.outbox_path,
    shared_secret = emitter.cfg.shared_secret,
    max_bytes = emitter.cfg.max_outbox_bytes,
  })
  if not emitter.outbox then
    log("ERROR %s - emitter disabled", tostring(emitter.outbox_error))
    return
  end

  emitter.events = Events.new(emitter.cfg, emit, GameApi)
  emitter.observers_ok = emitter.events:register_observers()

  if emitter.cfg.shared_secret == "change-me" then
    log("WARNING shared_secret is the default 'change-me'; set it in config.json")
  end

  emit("emitter_ready", { source = "cet", version = VERSION })
  log("v%s ready; config=%s outbox=%s", VERSION, tostring(emitter.config_source), emitter.outbox.path)
end)

registerForEvent("onUpdate", function(delta)
  if emitter.events then
    emitter.events:update(delta)
  end

  emitter.status_timer = emitter.status_timer + delta
  if emitter.cfg and emitter.status_timer >= 1.0 then
    emitter.status_timer = 0
    emitter.status = Status.read(emitter.cfg.status_path)
  end
end)

registerForEvent("onShutdown", function()
  if emitter.outbox then
    emit("emitter_shutdown", { source = "cet" })
    emitter.outbox:close()
  end
end)

registerForEvent("onOverlayOpen", function()
  emitter.overlay_open = true
end)

registerForEvent("onOverlayClose", function()
  emitter.overlay_open = false
end)

registerForEvent("onDraw", function()
  if not emitter.overlay_open then
    return
  end

  if ImGui.Begin("PiShock Emitter") then
    if not emitter.outbox then
      ImGui.Text("ERROR: " .. tostring(emitter.outbox_error))
    else
      ImGui.Text("Outbox: " .. emitter.outbox.path .. "  (" .. emitter.outbox.lines_written .. " events)")
      ImGui.Text("Last event: " .. emitter.last_event)
      local consumer = Status.describe(emitter.status, os.time(), 5)
      ImGui.Text("Consumer: " .. consumer)
      if emitter.status and emitter.status.estop == "1" then
        ImGui.Text("Consumer E-STOP: ENGAGED (clear it in the consumer)")
      end
      if not emitter.observers_ok and emitter.cfg.enable_quests then
        ImGui.Text("Quest observer unavailable")
      end
      if emitter.cfg.shared_secret == "change-me" then
        ImGui.Text("WARNING: default shared_secret")
      end
    end

    ImGui.Separator()
    if emitter.estop then
      ImGui.Text("IN-GAME E-STOP ENGAGED - events suppressed")
      if ImGui.Button("Clear in-game E-STOP") then
        clear_emergency_stop()
      end
    else
      ImGui.Text("Armed (shock allowed by game): " .. (emitter.armed and "YES" or "no"))
      if ImGui.Button(emitter.armed and "Disarm" or "Arm") then
        set_armed(not emitter.armed)
      end
      ImGui.SameLine()
      if ImGui.Button("Send test pulse") then
        emit("test_pulse", { source = "overlay" })
      end
      ImGui.Separator()
      if ImGui.Button("EMERGENCY STOP", 240, 40) then
        emergency_stop()
      end
    end
  end
  ImGui.End()
end)

-- Exposed for tests; CET ignores the return value of init.lua.
return emitter
