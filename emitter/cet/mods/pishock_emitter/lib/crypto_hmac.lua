-- Pure-Lua HMAC-SHA256 for the CET sandbox.
--
-- CET runs LuaJIT and exposes LuaJIT's `bit` library under the name `bit32`
-- (sol2 maps lib::bit32 -> luaopen_bit when built against LuaJIT). That library
-- returns *signed* 32-bit results and masks shift counts to 5 bits, so
-- rshift(x, 32) == x. All arithmetic below is written to be correct under both
-- LuaJIT `bit` and Lua 5.2 `bit32` semantics: values are re-normalised with
-- `% 2^32` and the 64-bit message length is encoded with plain arithmetic.

local CryptoHmac = {}

local bit = bit32 or bit
assert(bit, "crypto_hmac.lua requires bit32 or bit library")

local bxor = bit.bxor
local band = bit.band
local bnot = bit.bnot
local rshift = bit.rshift
local rrotate = bit.rrotate or bit.ror

local MOD32 = 2 ^ 32

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

local function u32(x)
  return x % MOD32
end

local function add32(...)
  local sum = 0
  for i = 1, select("#", ...) do
    sum = (sum + select(i, ...)) % MOD32
  end
  return sum
end

-- Append the 4 big-endian bytes of an unsigned 32-bit value.
local function push_be32(bytes, value)
  bytes[#bytes + 1] = math.floor(value / 0x1000000) % 256
  bytes[#bytes + 1] = math.floor(value / 0x10000) % 256
  bytes[#bytes + 1] = math.floor(value / 0x100) % 256
  bytes[#bytes + 1] = value % 256
end

local function sha256_words(msg)
  local bytes = {}
  for i = 1, #msg do
    bytes[i] = msg:byte(i)
  end
  local bit_len = #msg * 8

  bytes[#bytes + 1] = 0x80
  while (#bytes % 64) ~= 56 do
    bytes[#bytes + 1] = 0
  end
  push_be32(bytes, math.floor(bit_len / MOD32))
  push_be32(bytes, bit_len % MOD32)

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

  return { u32(h0), u32(h1), u32(h2), u32(h3), u32(h4), u32(h5), u32(h6), u32(h7) }
end

local function words_to_hex(words)
  local parts = {}
  for i = 1, #words do
    -- Split into 16-bit halves so formatting never depends on the runtime
    -- handling of %x for values >= 2^31.
    local v = words[i]
    parts[i] = string.format("%04x%04x", math.floor(v / 0x10000), v % 0x10000)
  end
  return table.concat(parts)
end

local function words_to_bin(words)
  local bytes = {}
  for i = 1, #words do
    push_be32(bytes, words[i])
  end
  local chars = {}
  for i = 1, #bytes do
    chars[i] = string.char(bytes[i])
  end
  return table.concat(chars)
end

function CryptoHmac.sha256_hex(msg)
  return words_to_hex(sha256_words(msg))
end

function CryptoHmac.hmac_sha256_hex(key, msg)
  local block_size = 64

  if #key > block_size then
    key = words_to_bin(sha256_words(key))
  end
  if #key < block_size then
    key = key .. string.rep("\0", block_size - #key)
  end

  local o_key_pad = {}
  local i_key_pad = {}
  for i = 1, block_size do
    local kb = key:byte(i)
    o_key_pad[i] = string.char(u32(bxor(kb, 0x5c)) % 256)
    i_key_pad[i] = string.char(u32(bxor(kb, 0x36)) % 256)
  end

  local inner = words_to_bin(sha256_words(table.concat(i_key_pad) .. msg))
  return words_to_hex(sha256_words(table.concat(o_key_pad) .. inner))
end

return CryptoHmac
