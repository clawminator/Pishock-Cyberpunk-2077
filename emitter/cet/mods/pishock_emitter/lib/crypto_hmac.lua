local CryptoHmac = {}

local bit = bit32 or bit
assert(bit, "crypto_hmac.lua requires bit32 or bit library")

local bxor = bit.bxor
local band = bit.band
local bnot = bit.bnot
local rshift = bit.rshift
local rrotate = bit.rrotate or bit.ror

local function str2bytes(s)
  local out = {}
  for i = 1, #s do
    out[i] = s:byte(i)
  end
  return out
end

local function bytes2str(bytes)
  local chars = {}
  for i = 1, #bytes do
    chars[i] = string.char(bytes[i])
  end
  return table.concat(chars)
end

local K = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
}

local function add32(...)
  local sum = 0
  for i = 1, select("#", ...) do
    sum = (sum + select(i, ...)) % 2^32
  end
  return sum
end

local function sha256(msg)
  local bytes = str2bytes(msg)
  local bit_len = #bytes * 8

  bytes[#bytes + 1] = 0x80
  while (#bytes % 64) ~= 56 do
    bytes[#bytes + 1] = 0
  end

  for i = 7, 0, -1 do
    bytes[#bytes + 1] = band(rshift(bit_len, i * 8), 0xff)
  end

  local h0,h1,h2,h3,h4,h5,h6,h7 =
    0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19

  local w = {}
  for chunk = 1, #bytes, 64 do
    for i = 0, 15 do
      local j = chunk + (i * 4)
      w[i] = (bytes[j] * 0x1000000) + (bytes[j + 1] * 0x10000) + (bytes[j + 2] * 0x100) + bytes[j + 3]
    end

    for i = 16, 63 do
      local s0 = bxor(rrotate(w[i - 15], 7), rrotate(w[i - 15], 18), rshift(w[i - 15], 3))
      local s1 = bxor(rrotate(w[i - 2], 17), rrotate(w[i - 2], 19), rshift(w[i - 2], 10))
      w[i] = add32(w[i - 16], s0, w[i - 7], s1)
    end

    local a,b,c,d,e,f,g,h = h0,h1,h2,h3,h4,h5,h6,h7

    for i = 0, 63 do
      local S1 = bxor(rrotate(e, 6), rrotate(e, 11), rrotate(e, 25))
      local ch = bxor(band(e, f), band(bnot(e), g))
      local temp1 = add32(h, S1, ch, K[i + 1], w[i])
      local S0 = bxor(rrotate(a, 2), rrotate(a, 13), rrotate(a, 22))
      local maj = bxor(band(a, b), band(a, c), band(b, c))
      local temp2 = add32(S0, maj)

      h = g
      g = f
      f = e
      e = add32(d, temp1)
      d = c
      c = b
      b = a
      a = add32(temp1, temp2)
    end

    h0 = add32(h0, a)
    h1 = add32(h1, b)
    h2 = add32(h2, c)
    h3 = add32(h3, d)
    h4 = add32(h4, e)
    h5 = add32(h5, f)
    h6 = add32(h6, g)
    h7 = add32(h7, h)
  end

  return string.format("%08x%08x%08x%08x%08x%08x%08x%08x", h0,h1,h2,h3,h4,h5,h6,h7)
end

function CryptoHmac.hmac_sha256_hex(key, msg)
  local block_size = 64

  if #key > block_size then
    key = bytes2str(str2bytes(sha256(key):gsub("..", function(h) return string.char(tonumber(h, 16)) end)))
  end

  if #key < block_size then
    key = key .. string.rep("\0", block_size - #key)
  end

  local o_key_pad = {}
  local i_key_pad = {}
  for i = 1, block_size do
    local kb = key:byte(i)
    o_key_pad[i] = string.char(bxor(kb, 0x5c))
    i_key_pad[i] = string.char(bxor(kb, 0x36))
  end

  local inner = sha256(table.concat(i_key_pad) .. msg)
  local inner_bytes = inner:gsub("..", function(h) return string.char(tonumber(h, 16)) end)
  return sha256(table.concat(o_key_pad) .. inner_bytes)
end

return CryptoHmac
