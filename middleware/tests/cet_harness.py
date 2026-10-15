"""Runs the real CET emitter (init.lua + lib/) under LuaJIT with a fake CET API.

The Lua environment mirrors CET's sandbox where it matters:
- LuaJIT 2.1 with LuaJIT's `bit` library exposed as `bit32` (what sol2 does)
- `os` limited to clock/date/difftime/time (+ remove/rename), so any use of
  os.execute or similar fails exactly like it would in game
- io.open relative to the mod directory (the test chdirs into it)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
from lupa import luajit21  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MOD_SOURCE = REPO_ROOT / "emitter" / "cet" / "mods" / "pishock_emitter"

FAKE_CET = r"""
FAKE_CET_STATE = {
  events = {}, hotkeys = {}, observers = {}, notifications = {}, drawn = {},
  player_present = false, player_throws = false,
  health = 400, max_health = 400, combat = false,
  journal = {}, click = nil,
}

function registerForEvent(name, fn) FAKE_CET_STATE.events[name] = fn end
function registerHotkey(id, label, fn) FAKE_CET_STATE.hotkeys[id] = fn end
function Observe(cls, method, fn) FAKE_CET_STATE.observers[cls .. "::" .. method] = fn end
function IsDefined(x) return x ~= nil end

gamedataStatPoolType = { Health = "Health" }
gamedataStatType = { Health = "Health" }
gameJournalEntryState = { Inactive = 0, Active = 1, Succeeded = 2, Failed = 3 }

local Player = {}
Player.__index = Player
function Player:GetEntityID() return "player-entity" end
function Player:IsInCombat() return FAKE_CET_STATE.combat end
function Player:SetWarningMessage(m) table.insert(FAKE_CET_STATE.notifications, m) end
local player = setmetatable({}, Player)

Game = {
  GetPlayer = function()
    if FAKE_CET_STATE.player_throws then error("not ready") end
    if FAKE_CET_STATE.player_present then return player end
    return nil
  end,
  GetStatPoolsSystem = function()
    return { GetStatPoolValue = function(_, id, kind, perc) return FAKE_CET_STATE.health end }
  end,
  GetStatsSystem = function()
    return { GetStatValue = function(_, id, kind) return FAKE_CET_STATE.max_health end }
  end,
  GetJournalManager = function()
    return {
      GetEntry = function(_, hash) return FAKE_CET_STATE.journal[hash] end,
      GetEntryState = function(_, entry) return entry.state end,
    }
  end,
}

function FAKE_CET_STATE.add_quest(hash, id, title, state)
  FAKE_CET_STATE.journal[hash] = {
    id = id, state = state,
    GetTitle = function(self, jm) return title end,
  }
end

ImGui = {
  Begin = function(title) return true end,
  End = function() end,
  Text = function(t) table.insert(FAKE_CET_STATE.drawn, t) end,
  Separator = function() end,
  SameLine = function() end,
  Button = function(label) table.insert(FAKE_CET_STATE.drawn, "[" .. label .. "]"); return FAKE_CET_STATE.click == label end,
}

-- CET sandbox: os is reduced to a handful of functions.
local real_os = os
os = {
  clock = real_os.clock, date = real_os.date, difftime = real_os.difftime, time = real_os.time,
  remove = real_os.remove, rename = real_os.rename,
}
bit32 = bit
bit = nil
"""


class CetHarness:
    def __init__(self, mod_dir: Path) -> None:
        self.mod_dir = mod_dir
        self.lua = luajit21.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = [[{mod_dir.as_posix()}/?.lua;]] .. package.path")
        self.lua.execute(FAKE_CET)
        self.cet = self.lua.globals().FAKE_CET_STATE
        self.emitter = None

    # --- lifecycle -------------------------------------------------------
    def load(self):
        self.emitter = self.lua.eval('dofile("init.lua")')
        return self.emitter

    def fire(self, name: str, *args):
        fn = self.cet.events[name]
        assert fn is not None, f"event {name} not registered"
        return fn(*args)

    def init(self):
        self.load()
        self.fire("onInit")
        return self

    def tick(self, seconds: float, dt: float = 0.05) -> None:
        steps = max(1, int(round(seconds / dt)))
        for _ in range(steps):
            self.fire("onUpdate", dt)

    def hotkey(self, name: str) -> None:
        self.cet.hotkeys[name]()

    def draw(self, click: str | None = None) -> list[str]:
        self.cet.drawn = self.lua.table()
        self.cet.click = click
        self.fire("onOverlayOpen")
        self.fire("onDraw")
        self.cet.click = None
        return list(self.cet.drawn.values())

    def observer(self, key: str):
        return self.cet.observers[key]

    # --- player state ----------------------------------------------------
    def spawn_player(self, health: float = 400, max_health: float = 400, warmup: float = 3.5) -> None:
        self.cet.player_present = True
        self.cet.health = health
        self.cet.max_health = max_health
        self.tick(warmup)

    def set_health(self, value: float, settle: float = 0.3) -> None:
        self.cet.health = value
        self.tick(settle)

    # --- outbox ----------------------------------------------------------
    @property
    def outbox(self) -> Path:
        return self.mod_dir / "outbox" / "events.jsonl"

    def lines(self) -> list[str]:
        path = self.outbox
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def make_lua():
    """Bare LuaJIT runtime that can require the emitter's lib/ modules."""

    runtime = luajit21.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(f"package.path = [[{MOD_SOURCE.as_posix()}/?.lua;]] .. package.path")
    runtime.execute("bit32 = bit; bit = nil")
    return runtime


def make_mod_copy(tmp_path: Path, secret: str | None = "test-secret") -> Path:
    mod_dir = tmp_path / "pishock_emitter"
    shutil.copytree(MOD_SOURCE, mod_dir, ignore=shutil.ignore_patterns("config.json", "*.jsonl", "consumer_status.txt"))
    if secret is not None:
        cfg = (mod_dir / "config.example.json").read_text(encoding="utf-8").replace('"change-me"', f'"{secret}"')
        (mod_dir / "config.json").write_text(cfg, encoding="utf-8")
    return mod_dir


__all__ = ["CetHarness", "make_lua", "make_mod_copy", "MOD_SOURCE", "REPO_ROOT"]
