"""Tests for the CET Lua emitter, executed under LuaJIT 2.1 (CET's runtime)."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil

import pytest

from middleware.protocol import parse_line
from middleware.security import verify_signature
from middleware.tests.cet_harness import CetHarness


def _events(harness: CetHarness) -> list[dict]:
    out = []
    for line in harness.lines():
        parsed = parse_line(line)
        assert parsed is not None, f"unparseable line: {line!r}"
        assert parsed.format == "jsonl"
        assert verify_signature(parsed.body.encode("utf-8"), parsed.signature, "test-secret"), line
        assert json.loads(line)["event"] == json.loads(parsed.body)  # every line is valid JSON too
        out.append(json.loads(parsed.body))
    return out


def _types(harness: CetHarness) -> list[str]:
    return [e["event_type"] for e in _events(harness)]


# --- crypto / encoding --------------------------------------------------------

@pytest.mark.parametrize(
    "key,msg",
    [
        ("test-secret", ""),
        ("test-secret", "abc"),
        ("test-secret", "a" * 55),  # padding boundary
        ("test-secret", "a" * 56),
        ("test-secret", "a" * 64),
        ("test-secret", "x" * 1000),
        ("k" * 64, "block-sized key"),
        ("k" * 100, "long key gets hashed"),
        ("s3cr3t", '{"context":{"title":"été — \U0001f600"},"event_type":"x"}'),
    ],
)
def test_lua_hmac_matches_python(lua, key, msg):
    hmac_mod = lua.eval('require("lib/crypto_hmac")')
    expected = hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    assert hmac_mod.hmac_sha256_hex(key, msg) == expected


def test_lua_sha256_matches_python(lua):
    hmac_mod = lua.eval('require("lib/crypto_hmac")')
    for msg in ["", "abc", "q" * 200]:
        assert hmac_mod.sha256_hex(msg) == hashlib.sha256(msg.encode()).hexdigest()


def test_json_encoder_output_is_valid_sorted_json(lua):
    encode = lua.eval('require("lib/json_min")').encode
    value = lua.eval(
        '{ b = 1, a = "x\\"y\\\\z\\n\\1", c = { 1, 2.5, true }, d = {}, e = 0/0, f = 1/0, g = 37.25, h = -3 }'
    )
    text = encode(value)
    assert text.startswith('{"a":')
    decoded = json.loads(text)
    assert decoded == {"a": 'x"y\\z\n\x01', "b": 1, "c": [1, 2.5, True], "d": {}, "e": None, "f": None, "g": 37.25, "h": -3}


def test_config_parser_reads_flat_json(lua):
    parse = lua.eval('require("lib/config")').parse_flat
    cfg = parse('{"shared_secret": "abc-123", "sample_interval_s": 0.25, "enable_heal": false, "max_outbox_bytes": 1048576}')
    assert cfg["shared_secret"] == "abc-123"
    assert cfg["sample_interval_s"] == 0.25
    assert cfg["enable_heal"] is False
    assert cfg["max_outbox_bytes"] == 1048576


# --- full emitter under fake CET -------------------------------------------------

def test_init_writes_signed_ready_event(cet):
    cet.init()
    events = _events(cet)
    assert [e["event_type"] for e in events] == ["emitter_ready"]
    ready = events[0]
    assert ready["armed"] is False
    assert ready["seq"] == 1
    assert ready["session_id"].startswith("cp77-")
    assert ready["context"]["version"] == "1.0.0"
    assert ready["ts_ms"] % 1000 == 0 and ready["ts_ms"] > 1_600_000_000_000


def test_outbox_is_truncated_on_each_start(cet):
    cet.outbox.write_text("old line\n", encoding="utf-8")
    cet.init()
    assert _types(cet) == ["emitter_ready"]


def test_damage_is_detected_from_health_drop(cet):
    cet.init()
    cet.spawn_player(health=400, max_health=400)
    cet.set_health(300)
    damage = [e for e in _events(cet) if e["event_type"] == "player_damaged"]
    assert len(damage) == 1
    assert damage[0]["context"] == {"source": "health_poll", "damage": 100, "max_health": 400, "health": 300}


def test_warmup_suppresses_load_jumps(cet):
    cet.init()
    cet.cet.player_present = True
    cet.cet.health = 50
    cet.tick(0.5)
    cet.cet.health = 400  # save finished loading
    cet.tick(3.5)
    assert _types(cet) == ["emitter_ready"]


def test_small_damage_accumulates_until_threshold(cet):
    cet.init()
    cet.spawn_player(health=1000, max_health=1000)
    for value in (997, 994, 991):  # 3 HP each, threshold is 1% = 10 HP
        cet.set_health(value)
    assert "player_damaged" not in _types(cet)
    cet.set_health(988)
    damage = [e for e in _events(cet) if e["event_type"] == "player_damaged"]
    assert len(damage) == 1 and damage[0]["context"]["damage"] == 12


def test_heal_detected_but_slow_regen_ignored(cet):
    cet.init()
    cet.spawn_player(health=200, max_health=400)
    for hp in range(201, 230):  # ~1 HP per sample: regeneration
        cet.set_health(hp, settle=0.2)
    assert "player_healed" not in _types(cet)
    cet.set_health(330)  # +100 in one go (25%)
    healed = [e for e in _events(cet) if e["event_type"] == "player_healed"]
    assert len(healed) == 1
    assert healed[0]["context"]["amount"] >= 40


def test_death_then_revive_emits_no_heal(cet):
    cet.init()
    cet.spawn_player(health=100, max_health=400)
    cet.set_health(0)
    types = _types(cet)
    assert types[-2:] == ["player_damaged", "player_death"]
    cet.set_health(400)
    cet.tick(4)
    assert _types(cet) == types  # nothing new after revival


def test_combat_transitions(cet):
    cet.init()
    cet.spawn_player()
    cet.cet.combat = True
    cet.tick(0.6)
    cet.cet.combat = False
    cet.tick(0.6)
    assert _types(cet)[-2:] == ["combat_start", "combat_end"]


def test_quest_completion_observer(cet):
    cet.init()
    observer = cet.observer("JournalNotificationQueue::OnJournalUpdate")
    assert observer is not None
    cet.cet.add_quest("h1", "q_heist", "The Heist", 2)
    cet.cet.add_quest("h2", "q_other", "Active Quest", 1)
    quest_class = cet.lua.eval('{ value = "gameJournalQuest" }')
    observer(None, "h2", quest_class)  # not succeeded
    observer(None, "h1", cet.lua.eval('{ value = "gameJournalQuestObjective" }'))  # not a quest
    observer(None, "h1", quest_class)
    observer(None, "h1", quest_class)  # duplicate
    observer(None, "missing", quest_class)
    quests = [e for e in _events(cet) if e["event_type"] == "quest_completed"]
    assert len(quests) == 1
    assert quests[0]["context"] == {"source": "journal", "quest_id": "q_heist", "title": "The Heist"}


def test_arming_marks_subsequent_events(cet):
    cet.init()
    cet.spawn_player()
    cet.hotkey("pishock_toggle_armed")
    cet.set_health(350)
    events = _events(cet)
    assert events[-2]["event_type"] == "armed_changed" and events[-2]["context"] == {"armed": True}
    assert events[-1]["event_type"] == "player_damaged" and events[-1]["armed"] is True
    assert "PiShock: ARMED" in cet.cet.notifications.values()


def test_emergency_stop_disarms_and_suppresses_until_cleared(cet):
    cet.init()
    cet.spawn_player()
    cet.hotkey("pishock_toggle_armed")
    cet.hotkey("pishock_emergency_stop")
    cet.set_health(300)
    cet.hotkey("pishock_test_pulse")
    cet.hotkey("pishock_toggle_armed")  # arming refused while stopped
    events = _events(cet)
    assert events[-1]["event_type"] == "emergency_stop"
    assert events[-1]["armed"] is False

    drawn = cet.draw()
    assert any("E-STOP ENGAGED" in t for t in drawn)
    cet.draw(click="Clear in-game E-STOP")
    cet.set_health(200)
    types = _types(cet)
    assert types[-2:] == ["emergency_stop_cleared", "player_damaged"]
    assert _events(cet)[-1]["armed"] is False  # stays disarmed after clearing


def test_overlay_buttons(cet):
    cet.init()
    drawn = cet.draw()
    assert "[Arm]" in drawn and "[EMERGENCY STOP]" in drawn
    assert any(t.startswith("Consumer: not detected") for t in drawn)
    cet.draw(click="Send test pulse")
    cet.draw(click="EMERGENCY STOP")
    assert _types(cet)[-2:] == ["test_pulse", "emergency_stop"]


def test_overlay_not_drawn_when_closed(cet):
    cet.init()
    cet.fire("onDraw")
    assert len(list(cet.cet.drawn.values())) == 0


def test_survives_missing_or_throwing_player(cet):
    cet.init()
    cet.tick(2)  # no player (main menu)
    cet.cet.player_present = True
    cet.cet.player_throws = True
    cet.tick(2)
    cet.cet.player_throws = False
    cet.cet.combat = True
    cet.tick(1)
    cet.hotkey("pishock_toggle_armed")
    assert _types(cet) == ["emitter_ready", "armed_changed"]


def test_shutdown_event_and_close(cet):
    cet.init()
    cet.fire("onShutdown")
    assert _types(cet)[-1] == "emitter_shutdown"


def test_falls_back_to_mod_root_when_outbox_dir_missing(cet):
    shutil.rmtree(cet.mod_dir / "outbox")
    cet.init()
    fallback = cet.mod_dir / "pishock_events.jsonl"
    assert fallback.exists()
    assert parse_line(fallback.read_text(encoding="utf-8").splitlines()[0]) is not None


def test_default_secret_warning_without_config_json(cet):
    (cet.mod_dir / "config.json").unlink()
    cet.init()
    assert any("default shared_secret" in t for t in cet.draw())
    line = cet.lines()[0]
    parsed = parse_line(line)
    assert verify_signature(parsed.body.encode(), parsed.signature, "change-me")


def test_outbox_size_cap_truncates(cet):
    cfg = (cet.mod_dir / "config.json").read_text(encoding="utf-8").replace("10485760", "2000")
    (cet.mod_dir / "config.json").write_text(cfg, encoding="utf-8")
    cet.init()
    for _ in range(30):
        cet.hotkey("pishock_test_pulse")
    assert cet.outbox.stat().st_size <= 2000
    assert all(parse_line(line) for line in cet.lines())
