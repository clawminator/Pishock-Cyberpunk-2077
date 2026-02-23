local JsonMin = {}

local function escape_str(value)
  return value
    :gsub('\\', '\\\\')
    :gsub('"', '\\"')
    :gsub('\b', '\\b')
    :gsub('\f', '\\f')
    :gsub('\n', '\\n')
    :gsub('\r', '\\r')
    :gsub('\t', '\\t')
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
  return count == max_i
end

local function encode_value(v)
  local t = type(v)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return v and "true" or "false"
  elseif t == "number" then
    return tostring(v)
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
      parts[#parts + 1] = encode_value(key) .. ":" .. encode_value(v[key])
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end

  error("Unsupported JSON type: " .. t)
end

function JsonMin.encode(value)
  return encode_value(value)
end

return JsonMin
