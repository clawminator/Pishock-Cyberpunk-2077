"""Tests for the file-based outbox consumer."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from middleware.config import SafetyConfig
from middleware.file_ingest import Ingester, OutboxTailer, write_status
from middleware.output import SimulatedOutput
from middleware.protocol import build_line
from middleware.safety import EmergencyStop
from middleware.tests.conftest import make_config

NOW = 1_800_000_000.0


def _event(event_type="player_damaged", ts_s=NOW, armed=True, **context):
    return {
        "event_type": event_type,
        "ts_ms": int(ts_s * 1000),
        "session_id": "s",
        "armed": armed,
        "seq": 1,
        "context": context,
    }


@pytest.fixture
def make_ingester(tmp_path):
    def factory(**cfg_overrides):
        cfg_overrides.setdefault(
            "safety", SafetyConfig(max_actions_per_minute=1000, global_cooldown_ms=0, max_event_age_s=10, estop_file=str(tmp_path / "ESTOP"))
        )
        cfg = make_config(**cfg_overrides)
        output = SimulatedOutput()
        clock = {"now": NOW}
        ingester = Ingester(cfg, output, clock=lambda: clock["now"])
        ingester.clock_state = clock
        return ingester, output

    return factory


def test_valid_damage_event_is_simulated(make_ingester):
    ingester, output = make_ingester()
    outcome = ingester.process_line(build_line(_event(damage=100, max_health=400), "test-secret"))
    assert outcome.status == "sent"
    # allow_shock is false -> fallback vibrate, 25% of 100 capped at max_intensity 20
    assert output.history[0][1].mode == "vibrate"
    assert output.history[0][1].intensity == 20


def test_shock_when_allowed_and_armed(make_ingester):
    ingester, output = make_ingester(allow_shock=True, max_intensity=100)
    ingester.process_line(build_line(_event(damage=100, max_health=400), "test-secret"))
    assert output.history[0][1].mode == "shock" and output.history[0][1].intensity == 25


def test_invalid_signature_rejected(make_ingester):
    ingester, output = make_ingester()
    outcome = ingester.process_line(build_line(_event(damage=1, max_health=4), "wrong-secret"))
    assert (outcome.status, outcome.reason) == ("skipped", "invalid_signature")
    assert output.history == []


def test_tampered_body_rejected(make_ingester):
    ingester, _ = make_ingester()
    line = build_line(_event(damage=10, max_health=400), "test-secret").replace('"damage":10', '"damage":400')
    assert ingester.process_line(line).reason == "invalid_signature"


def test_legacy_tab_format_still_accepted(make_ingester):
    ingester, output = make_ingester()
    body = json.dumps(_event(damage=100, max_health=400), separators=(",", ":"))
    sig = hmac.new(b"test-secret", body.encode(), hashlib.sha256).hexdigest()
    assert ingester.process_line(f"{sig}\t{body}\n").status == "sent"
    assert ingester.process_line(f"deadbeef\t{body}\n").reason == "malformed_line"


@pytest.mark.parametrize("line", ["", "garbage", "{}", '{"v":1,"sig":"zz","event":{}}'])
def test_malformed_lines(make_ingester, line):
    ingester, _ = make_ingester()
    assert ingester.process_line(line).reason == "malformed_line"


def test_stale_and_future_events_dropped(make_ingester):
    ingester, output = make_ingester()
    assert ingester.process_line(build_line(_event(ts_s=NOW - 60, damage=1, max_health=4), "test-secret")).reason == "stale_event"
    assert ingester.process_line(build_line(_event(ts_s=NOW + 60, damage=1, max_health=4), "test-secret")).reason == "stale_event"
    no_ts = _event(damage=1, max_health=4)
    del no_ts["ts_ms"]
    assert ingester.process_line(build_line(no_ts, "test-secret")).reason == "missing_ts"
    assert output.history == []


def test_info_events_never_produce_output(make_ingester):
    ingester, output = make_ingester()
    for event_type in ("emitter_ready", "armed_changed", "combat_end", "emitter_shutdown", "emergency_stop_cleared"):
        assert ingester.process_line(build_line(_event(event_type), "test-secret")).status == "info"
    assert output.history == []


def test_unmapped_event_skipped(make_ingester):
    ingester, _ = make_ingester()
    assert ingester.process_line(build_line(_event("something_new"), "test-secret")).reason == "unmapped"


def test_emergency_stop_event_latches_even_unsigned(make_ingester):
    ingester, output = make_ingester()
    outcome = ingester.process_line(build_line(_event("emergency_stop"), "WRONG"))
    assert outcome.status == "estop"
    assert ingester.estop.is_engaged()
    assert ingester.process_line(build_line(_event("test_pulse"), "test-secret")).reason == "emergency_stop"
    # emergency_stop_cleared from the game does NOT clear the consumer latch
    ingester.process_line(build_line(_event("emergency_stop_cleared"), "test-secret"))
    assert ingester.process_line(build_line(_event("test_pulse"), "test-secret")).reason == "emergency_stop"
    assert output.history == []
    ingester.estop.clear()
    assert ingester.process_line(build_line(_event("test_pulse"), "test-secret")).status == "sent"


def test_global_rate_limit_and_gap(make_ingester, tmp_path):
    ingester, output = make_ingester(
        safety=SafetyConfig(max_actions_per_minute=3, global_cooldown_ms=500, max_event_age_s=10, estop_file=str(tmp_path / "E"))
    )
    clock = ingester.clock_state
    results = []
    for i in range(6):
        clock["now"] = NOW + i * 0.25
        results.append(ingester.process_line(build_line(_event("test_pulse", ts_s=clock["now"]), "test-secret")).reason or "sent")
    assert results == ["sent", "global_cooldown", "sent", "global_cooldown", "sent", "global_cooldown"]
    clock["now"] = NOW + 2
    assert ingester.process_line(build_line(_event("test_pulse", ts_s=clock["now"]), "test-secret")).reason == "rate_limit"
    clock["now"] = NOW + 61
    assert ingester.process_line(build_line(_event("test_pulse", ts_s=clock["now"]), "test-secret")).status == "sent"
    assert len(output.history) == 4


def test_failed_output_is_reported(make_ingester):
    ingester, _ = make_ingester()

    class Broken:
        name = "broken"

        def send(self, action, event):
            from middleware.output import OutputResult

            return OutputResult(ok=False, detail="nope")

    ingester.output = Broken()
    assert ingester.process_line(build_line(_event("test_pulse"), "test-secret")).reason == "output_failed:nope"


# --- tailer -------------------------------------------------------------------

def test_tailer_starts_at_end_and_reads_only_new_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"old-1\nold-2\n")
    tailer = OutboxTailer(path)
    assert tailer.poll() == []
    with path.open("ab") as fh:
        fh.write(b"new-1\nnew-")
    assert tailer.poll() == ["new-1"]
    with path.open("ab") as fh:
        fh.write(b"2\r\n")
    assert tailer.poll() == ["new-2"]


def test_tailer_from_start(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"a\nb\n")
    assert OutboxTailer(path, start_at_end=False).poll() == ["a", "b"]


@pytest.mark.parametrize("start_at_end", [True, False])
def test_tailer_missing_file_then_created(tmp_path, start_at_end):
    # Consumer started before the game: the whole new file must be read.
    path = tmp_path / "events.jsonl"
    tailer = OutboxTailer(path, start_at_end=start_at_end)
    assert tailer.poll() == []
    path.write_bytes(b"x\ny\n")
    assert tailer.poll() == ["x", "y"]


def test_tailer_detects_truncation(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"first-session-line-1\nfirst-session-line-2\n")
    tailer = OutboxTailer(path, start_at_end=False)
    assert len(tailer.poll()) == 2
    path.write_bytes(b"new\n")  # emitter restarted (shorter file)
    assert tailer.poll() == ["new"]
    assert tailer.resets == 1


def test_tailer_detects_truncation_and_regrowth(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"session-A-1\n")
    tailer = OutboxTailer(path, start_at_end=False)
    assert tailer.poll() == ["session-A-1"]
    path.write_bytes(b"session-B-1\nsession-B-2\n")  # truncated then grew past old offset
    assert tailer.poll() == ["session-B-1", "session-B-2"]


def test_status_file_written(make_ingester, tmp_path):
    ingester, _ = make_ingester()
    status = tmp_path / "consumer_status.txt"
    write_status(status, ingester, "running")
    text = status.read_text(encoding="utf-8")
    assert "state=running" in text and "output=simulated" in text and "estop=0" in text
    assert abs(int(text.split("ts=")[1].split()[0]) - time.time()) < 5


def test_estop_file_helper(tmp_path):
    stop = EmergencyStop(tmp_path / "sub" / "ESTOP")
    assert not stop.is_engaged()
    stop.engage("because")
    assert stop.is_engaged() and "because" in stop.reason()
    assert stop.clear() is True
    assert not stop.is_engaged()
    assert stop.clear() is False
