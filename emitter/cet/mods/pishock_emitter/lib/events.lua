local Events = {}
Events.__index = Events

function Events.new(emit_fn)
  return setmetatable({ emit = emit_fn }, Events)
end

function Events:register_observers()
  -- Discovery-first placeholders. Replace class/method names with NativeDB verified hooks.
  -- Example:
  -- ObserveAfter("SomeClass", "SomeMethod", function(self, ...)
  --   self.emit("some_event", { source = "cet" })
  -- end)

  -- Simple startup event to validate the file outbox path.
  self.emit("emitter_ready", { source = "cet" })
end

return Events
