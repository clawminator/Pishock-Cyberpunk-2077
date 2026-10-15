-- Loads the emitter's flat config.json without depending on a JSON library.
--
-- Only flat string / number / boolean keys are supported, which is all the
-- emitter needs. Unknown keys are ignored; missing keys fall back to DEFAULTS.

local Config = {}

Config.DEFAULTS = {
  shared_secret = "change-me",
  outbox_path = "outbox/events.jsonl",
  status_path = "outbox/consumer_status.txt",
  session_id_prefix = "cp77",
  max_outbox_bytes = 10 * 1024 * 1024,

  -- Health sampling (seconds / percent of max health)
  sample_interval_s = 0.2,
  warmup_s = 3.0,
  min_damage_pct = 1.0,
  heal_threshold_pct = 10.0,
  heal_window_s = 3.0,
  combat_poll_s = 0.5,

  -- Individual detectors
  enable_damage = true,
  enable_heal = true,
  enable_death = true,
  enable_combat = true,
  enable_quests = true,
}

local function read_file(path)
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local content = f:read("*a")
  f:close()
  return content
end

local function unescape(s)
  return (s:gsub('\\(["\\/])', "%1"))
end

-- Parse a flat JSON object into a Lua table. Nested values are skipped.
function Config.parse_flat(content)
  local out = {}
  if type(content) ~= "string" then
    return out
  end
  -- Strings may not contain a double quote (keep secrets to [A-Za-z0-9_-]).
  for key, value in content:gmatch('"([%w_]+)"%s*:%s*"([^"]*)"') do
    out[key] = unescape(value)
  end
  for key, value in content:gmatch('"([%w_]+)"%s*:%s*(-?%d+%.?%d*[eE]?[-+]?%d*)%s*[,}]') do
    out[key] = tonumber(value)
  end
  for key, value in content:gmatch('"([%w_]+)"%s*:%s*(%a+)%s*[,}]') do
    if value == "true" then
      out[key] = true
    elseif value == "false" then
      out[key] = false
    end
  end
  return out
end

-- Returns cfg, source where source is the file that was read (or nil).
function Config.load(paths)
  local cfg = {}
  for k, v in pairs(Config.DEFAULTS) do
    cfg[k] = v
  end

  for _, path in ipairs(paths) do
    local content = read_file(path)
    if content then
      for k, v in pairs(Config.parse_flat(content)) do
        if Config.DEFAULTS[k] ~= nil and type(v) == type(Config.DEFAULTS[k]) then
          cfg[k] = v
        end
      end
      return cfg, path
    end
  end
  return cfg, nil
end

return Config
