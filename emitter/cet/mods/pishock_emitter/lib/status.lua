-- Reads the status file the Python consumer writes next to the outbox, so the
-- overlay can show whether the consumer is running and whether its emergency
-- stop is engaged. Format: one `key=value` per line.

local Status = {}

function Status.parse(content)
  local out = {}
  if type(content) ~= "string" then
    return out
  end
  for line in content:gmatch("[^\r\n]+") do
    local key, value = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
    if key then
      out[key] = value
    end
  end
  return out
end

function Status.read(path)
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local content = f:read("*a")
  f:close()
  return Status.parse(content)
end

-- Summarise for display. `now_s` is os.time().
function Status.describe(status, now_s, stale_after_s)
  if status == nil or status.ts == nil then
    return "not detected", false
  end
  local age = now_s - (tonumber(status.ts) or 0)
  if status.state == "stopped" then
    return "stopped", false
  end
  if age > (stale_after_s or 5) then
    return string.format("not responding (%ds)", age), false
  end
  return string.format("running (%s output)", status.output or "?"), true
end

return Status
