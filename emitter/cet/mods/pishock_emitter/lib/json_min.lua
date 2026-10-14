-- Deterministic compact JSON encoder (sorted object keys, no whitespace).
--
-- Output is signed byte-for-byte, so it must be stable for a given input.

local JsonMin = {}

local function escape_char(c)
  local b = c:byte()
  if c == '"' then return '\\"' end
  if c == '\\' then return '\\\\' end
  if c == '\n' then return '\\n' end
  if c == '\r' then return '\\r' end
  if c == '\t' then return '\\t' end
  if c == '\b' then return '\\b' end
  if c == '\f' then return '\\f' end
  return string.format('\\u%04x', b)
end

local function escape_str(value)
  -- Escape quote, backslash and every control character (0x00-0x1f, 0x7f).
  return (value:gsub('[%c"\\]', escape_char))
end

local function is_array(tbl)
  local max_i = 0
  local count = 0
  for k, _ in pairs(tbl) do
    if type(k) ~= "number" or k < 1 or k % 1 ~= 0 then
      return false
    end
    if k > max_i then
      max_i = k
    end
    count = count + 1
  end
  -- Empty tables encode as objects: event contexts are always objects.
  return count > 0 and count == max_i
end

local function encode_number(v)
  if v ~= v or v == math.huge or v == -math.huge then
    return "null" -- NaN / Infinity are not valid JSON
  end
  if v % 1 == 0 and v > -1e15 and v < 1e15 then
    return string.format("%d", v)
  end
  return string.format("%.6g", v)
end

local function encode_value(v)
  local t = type(v)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return v and "true" or "false"
  elseif t == "number" then
    return encode_number(v)
  elseif t == "string" then
    return '"' .. escape_str(v) .. '"'
  elseif t == "table" then
    if is_array(v) then
      local parts = {}
      for i = 1, #v do
        parts[#parts + 1] = encode_value(v[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end

    local keys = {}
    for k, _ in pairs(v) do
      keys[#keys + 1] = tostring(k)
    end
    table.sort(keys)

    local parts = {}
    for _, key in ipairs(keys) do
      local value = v[key]
      if value == nil then
        value = v[tonumber(key)]
      end
      parts[#parts + 1] = encode_value(key) .. ":" .. encode_value(value)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end

  return encode_value(tostring(v))
end

function JsonMin.encode(value)
  return encode_value(value)
end

return JsonMin
