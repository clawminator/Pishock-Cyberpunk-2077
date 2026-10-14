"""Game emitter (Lua, under LuaJIT) -> JSONL file -> Python consumer -> output.

These tests run the real init.lua against a fake CET API, then feed the file it
wrote through the real consumer, exactly as in game.
"""

from __future__ import annotations

from middleware.config import SafetyConfig, load_config
from middleware.file_ingest import Ingester, OutboxTailer, write_status
from middleware.output import PiShockOutput, SimulatedOutput
from middleware.pishock_http import PiShockResult
from middleware.tests.cet_harness import MOD_SOURCE, REPO_ROOT
from middleware.tests.conftest import make_config


def _consume(harness, ingester):
    tailer = OutboxTailer(harness.outbox, start_at_end=False)
    return [ingester.process_line(line) for line in tailer.poll()]


def _safety(tmp_path):
    return SafetyConfig(max_actions_per_minute=1000, global_cooldown_ms=0, max_event_age_s=10, estop_file=str(tmp_path / "ESTOP"))


def test_gameplay_session_produces_expected_actions(cet, tmp_path):
    cet.init()
    cet.spawn_player(health=400, max_health=400)
    cet.set_health(300)               # 25% damage
    cet.set_health(400)               # +25% heal
    cet.cet.combat = True
    cet.tick(0.6)
    cet.hotkey("pishock_test_pulse")

    output = SimulatedOutput()
    ingester = Ingester(make_config(safety=_safety(tmp_path)), output)
    outcomes = _consume(cet, ingester)

    assert [o.status for o in outcomes] == ["info", "sent", "sent", "sent", "sent"]
    sent = [(event_type, a.mode, a.intensity) for event_type, a in output.history]
    assert sent == [
        ("player_damaged", "vibrate", 20),  # shock disabled -> fallback, 25 capped to 20
        ("player_healed", "vibrate", 10),
        ("combat_start", "vibrate", 6),
        ("test_pulse", "beep", 1),
    ]


def test_armed_damage_shocks_only_when_allowed(cet, tmp_path):
    cet.init()
    cet.spawn_player(health=400, max_health=400)
    cet.set_health(350)               # unarmed hit
    cet.hotkey("pishock_toggle_armed")
    cet.set_health(250)               # armed hit, 25%

    output = SimulatedOutput()
    ingester = Ingester(make_config(allow_shock=True, max_intensity=100, safety=_safety(tmp_path)), output)
    _consume(cet, ingester)
    assert [(a.mode, a.intensity) for _, a in output.history] == [("vibrate", 12), ("shock", 25)]


def test_wrong_secret_in_game_config_rejects_everything(cet, tmp_path):
    (cet.mod_dir / "config.json").write_text('{"shared_secret": "game-side-secret"}', encoding="utf-8")
    cet.init()
    cet.spawn_player()
    cet.set_health(100)
    output = SimulatedOutput()
    outcomes = _consume(cet, Ingester(make_config(safety=_safety(tmp_path)), output))
    assert {o.reason for o in outcomes} == {"invalid_signature"}
    assert output.history == []


def test_in_game_emergency_stop_blocks_live_hardware(cet, tmp_path):
    calls = []

    def fake_sender(**kwargs):
        calls.append(kwargs)
        return PiShockResult(ok=True, status_code=200, body="Operation Succeeded.")

    cfg = make_config(dry_run=False, allow_shock=True, safety=_safety(tmp_path))
    ingester = Ingester(cfg, output=None)
    ingester.output = PiShockOutput(cfg, is_stopped=ingester.estop.is_engaged, sender=fake_sender)

    cet.init()
    cet.spawn_player()
    cet.hotkey("pishock_toggle_armed")
    cet.set_health(300)
    _consume(cet, ingester)
    assert len(calls) == 1 and calls[0]["mode"] == "shock"

    tailer = OutboxTailer(cet.outbox)  # continue from current end
    tailer.poll()
    cet.hotkey("pishock_emergency_stop")
    cet.draw(click="Clear in-game E-STOP")  # game resumes emitting...
    cet.set_health(200)
    outcomes = [ingester.process_line(line) for line in tailer.poll()]
    assert [o.status for o in outcomes] == ["estop", "info", "skipped"]
    assert outcomes[-1].reason == "emergency_stop"  # ...but the consumer stays latched
    assert len(calls) == 1
    assert (tmp_path / "ESTOP").exists()


def test_consumer_status_visible_in_game_overlay(cet, tmp_path):
    cet.init()
    ingester = Ingester(make_config(safety=_safety(tmp_path)), SimulatedOutput())
    write_status(cet.mod_dir / "outbox" / "consumer_status.txt", ingester, "running")
    cet.tick(1.1)  # emitter re-reads status every second
    assert any(t == "Consumer: running (simulated output)" for t in cet.draw())

    ingester.estop.engage("test")
    write_status(cet.mod_dir / "outbox" / "consumer_status.txt", ingester, "stopped")
    cet.tick(1.1)
    drawn = cet.draw()
    assert "Consumer: stopped" in drawn
    assert any("Consumer E-STOP: ENGAGED" in t for t in drawn)


def test_example_configs_agree():
    """Out of the box, the example CET config and example YAML share a secret and path."""

    cfg = load_config(REPO_ROOT / "middleware" / "config.example.yaml")
    example = (MOD_SOURCE / "config.example.json").read_text(encoding="utf-8")
    assert f'"shared_secret": "{cfg.shared_secret}"' in example
    assert cfg.ingest.outbox_path.endswith("pishock_emitter/outbox/events.jsonl")
    assert '"outbox_path": "outbox/events.jsonl"' in example
