-- Append-only signed JSONL outbox.
--
-- Each line is a self-contained JSON object:
--
--   {"v":1,"sig":"<64 hex>","event":<event json>}
--
-- `sig` is HMAC-SHA256 over the exact bytes of <event json> as written, so the
-- consumer can verify the line without re-serialising anything.
--
-- CET's sandbox has no os.execute / mkdir, so the `outbox/` directory ships
-- with the mod. The file is truncated when the emitter starts (old events are
-- stale) and again if it grows past max_bytes; the consumer detects both.

local JsonMin = require("lib/json_min")
local CryptoHmac = require("lib/crypto_hmac")

local Outbox = {}
Outbox.__index = Outbox

Outbox.FORMAT_VERSION = 1
Outbox.FALLBACK_PATH = "pishock_events.jsonl"

function Outbox.encode_line(event_table, shared_secret)
  local json_body = JsonMin.encode(event_table)
  local sig_hex = CryptoHmac.hmac_sha256_hex(shared_secret, json_body)
  return string.format('{"v":%d,"sig":"%s","event":%s}\n', Outbox.FORMAT_VERSION, sig_hex, json_body)
end

-- opts: path, shared_secret, max_bytes
-- Returns outbox, nil on success or nil, error_message.
function Outbox.new(opts)
  local path = opts.path
  local handle, err = io.open(path, "w")
  if not handle then
    -- e.g. outbox/ was not copied with the mod: fall back to the mod root.
    local fallback_err = err
    path = Outbox.FALLBACK_PATH
    handle, err = io.open(path, "w")
    if not handle then
      return nil, string.format("cannot open outbox (%s; %s)", tostring(fallback_err), tostring(err))
    end
  end

  return setmetatable({
    handle = handle,
    path = path,
    shared_secret = opts.shared_secret,
    max_bytes = opts.max_bytes or (10 * 1024 * 1024),
    bytes_written = 0,
    lines_written = 0,
  }, Outbox), nil
end

function Outbox:emit(event_table)
  if not self.handle then
    return false
  end
  local line = Outbox.encode_line(event_table, self.shared_secret)

  if self.bytes_written + #line > self.max_bytes then
    self.handle:close()
    self.handle = io.open(self.path, "w")
    self.bytes_written = 0
    if not self.handle then
      return false
    end
  end

  self.handle:write(line)
  self.handle:flush()
  self.bytes_written = self.bytes_written + #line
  self.lines_written = self.lines_written + 1
  return true
end

function Outbox:close()
  if self.handle then
    self.handle:close()
    self.handle = nil
  end
end

return Outbox
