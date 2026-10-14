-- Thin, defensive wrapper around the CET / game APIs the emitter reads.
--
-- Every call is pcall-guarded: during loading screens, the main menu or after a
-- game patch these can be nil or throw, and the emitter must never break the
-- game. All APIs used here are in wide use by published CET mods:
--   Game.GetStatPoolsSystem():GetStatPoolValue(id, gamedataStatPoolType.Health, false)
--   Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Health)
--   PlayerPuppet:IsInCombat()
--   JournalNotificationQueue:OnJournalUpdate(hash, className)  (observer)
--   PlayerPuppet:SetWarningMessage(text)

local GameApi = {}

function GameApi.player()
  local ok, player = pcall(function()
    return Game.GetPlayer()
  end)
  if not ok or player == nil then
    return nil
  end
  if IsDefined ~= nil and not IsDefined(player) then
    return nil
  end
  return player
end

-- Returns current_health, max_health or nil when unavailable.
function GameApi.health()
  local player = GameApi.player()
  if not player then
    return nil
  end
  local ok, cur, max = pcall(function()
    local id = player:GetEntityID()
    local current = Game.GetStatPoolsSystem():GetStatPoolValue(id, gamedataStatPoolType.Health, false)
    local maximum = Game.GetStatsSystem():GetStatValue(id, gamedataStatType.Health)
    return current, maximum
  end)
  if not ok or type(cur) ~= "number" or type(max) ~= "number" or max <= 0 then
    return nil
  end
  return cur, max
end

-- Returns true / false, or nil when unavailable.
function GameApi.in_combat()
  local player = GameApi.player()
  if not player then
    return nil
  end
  local ok, value = pcall(function()
    return player:IsInCombat()
  end)
  if not ok then
    return nil
  end
  return value == true
end

-- Resolves a JournalNotificationQueue:OnJournalUpdate callback into a
-- completed-quest description, or nil if it is not a completed quest.
function GameApi.completed_quest(hash, class_name)
  local ok, result = pcall(function()
    if class_name == nil or class_name.value ~= "gameJournalQuest" then
      return nil
    end
    local journal = Game.GetJournalManager()
    local entry = journal:GetEntry(hash)
    if entry == nil then
      return nil
    end
    if journal:GetEntryState(entry) ~= gameJournalEntryState.Succeeded then
      return nil
    end
    local title = entry:GetTitle(journal)
    local id = entry.id
    return { id = id and tostring(id) or tostring(hash), title = title and tostring(title) or "" }
  end)
  if not ok then
    return nil
  end
  return result
end

-- Registers the journal observer. `handler(quest)` receives completed quests.
function GameApi.observe_quests(handler)
  if Observe == nil then
    return false
  end
  local ok = pcall(function()
    Observe("JournalNotificationQueue", "OnJournalUpdate", function(_, hash, class_name)
      local quest = GameApi.completed_quest(hash, class_name)
      if quest then
        handler(quest)
      end
    end)
  end)
  return ok
end

function GameApi.notify(message)
  local player = GameApi.player()
  if not player then
    return
  end
  pcall(function()
    player:SetWarningMessage(message)
  end)
end

return GameApi
