local Events = require("lib/events")
local Outbox = require("lib/outbox")

local CONFIG_PATH = "config.json"
local OUTBOX_PATH = "outbox/events.log"

local emitter = {
  armed = false,
  session_id = nil,
  seq = 0,
  outbox = nil,
  events = nil,
}

registerHotkey("pishock_emitter_toggle_armed", "PiShock Emitter: Toggle Armed", function()
  emitter.armed = not emitter.armed
  print(string.format("[pishock_emitter] armed=%s", tostring(emitter.armed)))
end)

registerForEvent("onInit", function()
  emitter.outbox = Outbox.new(CONFIG_PATH, OUTBOX_PATH)
  emitter.session_id = emitter.outbox:session_id()

  emitter.events = Events.new(function(event_type, context)
    emitter.seq = emitter.seq + 1
    emitter.outbox:emit({
      event_type = event_type,
      ts_ms = math.floor(os.clock() * 1000),
      session_id = emitter.session_id,
      armed = emitter.armed,
      context = context or {},
      seq = emitter.seq,
    })
  end)

  emitter.events:register_observers()
  print("[pishock_emitter] initialized; writing to outbox/events.log")
end)

registerForEvent("onShutdown", function()
  if emitter.outbox then
    emitter.outbox:close()
  end
end)
