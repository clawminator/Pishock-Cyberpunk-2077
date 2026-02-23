local JsonMin = require("lib/json_min")
local CryptoHmac = require("lib/crypto_hmac")

local Outbox = {}
Outbox.__index = Outbox

local function ensure_dir(path)
  local is_windows = package.config:sub(1, 1) == "\\"
  if is_windows then
    os.execute(string.format('if not exist "%s" mkdir "%s"', path, path))
  else
    os.execute(string.format('mkdir -p "%s"', path))
  end
end

local function load_config(config_path)
  local f = io.open(config_path, "r")
  if not f then
    return {
      shared_secret = "change-me",
      outbox_path = "outbox/events.log",
      session_id_prefix = "cp77",
    }
  end

  local content = f:read("*a")
  f:close()

  local shared_secret = content:match('"shared_secret"%s*:%s*"([^"]+)"') or "change-me"
  local outbox_path = content:match('"outbox_path"%s*:%s*"([^"]+)"') or "outbox/events.log"
  local session_id_prefix = content:match('"session_id_prefix"%s*:%s*"([^"]+)"') or "cp77"

  return {
    shared_secret = shared_secret,
    outbox_path = outbox_path,
    session_id_prefix = session_id_prefix,
  }
end

function Outbox.new(config_path, default_outbox_path)
  local cfg = load_config(config_path)
  local outbox_path = cfg.outbox_path or default_outbox_path

  ensure_dir("outbox")

  local handle, err = io.open(outbox_path, "a+")
  if not handle then
    error("Could not open outbox file: " .. tostring(err))
  end

  local self = setmetatable({
    handle = handle,
    shared_secret = cfg.shared_secret,
    _session_id = string.format("%s-%d", cfg.session_id_prefix, math.floor(os.time())),
  }, Outbox)

  return self
end

function Outbox:session_id()
  return self._session_id
end

function Outbox:emit(event_table)
  local json_body = JsonMin.encode(event_table)
  local sig_hex = CryptoHmac.hmac_sha256_hex(self.shared_secret, json_body)
  self.handle:write(sig_hex, "\t", json_body, "\n")
  self.handle:flush()
end

function Outbox:close()
  if self.handle then
    self.handle:close()
    self.handle = nil
  end
end

return Outbox
