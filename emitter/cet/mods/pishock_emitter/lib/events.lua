-- Game event detectors.
--
-- Damage / heal / death are derived from sampling the player's health stat
-- pool rather than hooking a specific damage callback: the stat-pool API is
-- stable across game patches and the same code path covers every damage
-- source (bullets, melee, fall damage, burning, quickhacks ...).
--
--   player_damaged  health dropped by >= min_damage_pct of max (accumulated)
--   player_healed   health rose by >= heal_threshold_pct within heal_window_s
--   player_death    health reached 0
--   combat_start    IsInCombat() false -> true   (combat_end on the reverse)
--   quest_completed journal reports a quest entry as Succeeded
--
-- `api` is lib/game_api in game and a fake in tests.

local Events = {}
Events.__index = Events

local function round2(x)
  return math.floor(x * 100 + 0.5) / 100
end

function Events.new(cfg, emit_fn, api)
  local self = setmetatable({
    cfg = cfg,
    emit = emit_fn,
    api = api,
    sample_timer = 0,
    combat_timer = 0,
    warmup = cfg.warmup_s,
    last_health = nil,
    pending_damage = 0,
    heal_accum = 0,
    heal_timer = 0,
    dead = false,
    in_combat = nil,
    seen_quests = {},
  }, Events)
  return self
end

function Events:register_observers()
  if self.cfg.enable_quests then
    return self.api.observe_quests(function(quest)
      self:on_quest_completed(quest)
    end)
  end
  return false
end

-- Forget the health baseline (player despawned, save loaded, revived ...).
function Events:reset_baseline()
  self.last_health = nil
  self.pending_damage = 0
  self.heal_accum = 0
  self.heal_timer = 0
  self.warmup = self.cfg.warmup_s
end

function Events:update(dt)
  self.sample_timer = self.sample_timer + dt
  if self.sample_timer >= self.cfg.sample_interval_s then
    local elapsed = self.sample_timer
    self.sample_timer = 0
    self:sample_health(elapsed)
  end

  if self.cfg.enable_combat then
    self.combat_timer = self.combat_timer + dt
    if self.combat_timer >= self.cfg.combat_poll_s then
      self.combat_timer = 0
      self:sample_combat()
    end
  end
end

function Events:sample_health(elapsed)
  local cur, max = self.api.health()
  if cur == nil then
    self:reset_baseline()
    return
  end

  -- Warm-up: absorb the health jumps that happen while a save loads. With
  -- warmup_s = 0 the first sample still has to become the baseline.
  if self.warmup > 0 or self.last_health == nil then
    self.warmup = self.warmup - elapsed
    self.last_health = cur
    self.dead = cur <= 0
    return
  end

  local cfg = self.cfg
  local delta = cur - self.last_health
  self.last_health = cur

  if self.dead then
    if cur > 0 then
      -- Revived / reloaded: start over without emitting a giant heal.
      self.dead = false
      self:reset_baseline()
    end
    return
  end

  if delta < 0 then
    self.pending_damage = self.pending_damage - delta
    self.heal_accum = 0
    self.heal_timer = 0
  elseif delta > 0 then
    self.pending_damage = 0
    self.heal_accum = self.heal_accum + delta
  end

  local died = cur <= 0
  local min_damage = max * cfg.min_damage_pct / 100
  if cfg.enable_damage and self.pending_damage > 0 and (died or self.pending_damage >= min_damage) then
    self.emit("player_damaged", {
      source = "health_poll",
      damage = round2(self.pending_damage),
      max_health = round2(max),
      health = round2(math.max(cur, 0)),
    })
    self.pending_damage = 0
  end

  if died then
    self.dead = true
    self.pending_damage = 0
    self.heal_accum = 0
    if cfg.enable_death then
      self.emit("player_death", { source = "health_poll", max_health = round2(max) })
    end
    return
  end

  if self.heal_accum > 0 then
    self.heal_timer = self.heal_timer + elapsed
    if self.heal_accum >= max * cfg.heal_threshold_pct / 100 then
      if cfg.enable_heal then
        self.emit("player_healed", {
          source = "health_poll",
          amount = round2(self.heal_accum),
          max_health = round2(max),
          health = round2(cur),
        })
      end
      self.heal_accum = 0
      self.heal_timer = 0
    elseif self.heal_timer >= cfg.heal_window_s then
      -- Slow regeneration, not a heal.
      self.heal_accum = 0
      self.heal_timer = 0
    end
  end
end

function Events:sample_combat()
  local value = self.api.in_combat()
  if value == nil then
    self.in_combat = nil
    return
  end
  if self.in_combat == nil then
    self.in_combat = value -- baseline only
    return
  end
  if value ~= self.in_combat then
    self.in_combat = value
    self.emit(value and "combat_start" or "combat_end", { source = "combat_poll" })
  end
end

function Events:on_quest_completed(quest)
  if self.seen_quests[quest.id] then
    return
  end
  self.seen_quests[quest.id] = true
  self.emit("quest_completed", { source = "journal", quest_id = quest.id, title = quest.title })
end

return Events
