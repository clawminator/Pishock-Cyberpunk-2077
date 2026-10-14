"""Config validation, PiShock client, CLIs, setup wizard and mod installer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from middleware import install_mod, pishock_http, safety, setup_wizard
from middleware.config import ConfigError, load_config
from middleware.protocol import build_line, parse_line, sign
from middleware.simulate import Simulator

REPO_ROOT = Path(__file__).resolve().parents[2]
MOD_SOURCE = REPO_ROOT / "emitter" / "cet" / "mods" / "pishock_emitter"
EXAMPLE = REPO_ROOT / "middleware" / "config.example.yaml"


def _write_cfg(tmp_path: Path, text_replacements: dict[str, str] | None = None) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("middleware/state/ESTOP", (tmp_path / "ESTOP").as_posix())
    for old, new in (text_replacements or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- config -------------------------------------------------------------------

def test_example_config_loads_with_safe_defaults():
    cfg = load_config(EXAMPLE)
    assert cfg.dry_run is True
    assert cfg.allow_shock is False
    assert cfg.event_mappings["player_damaged"]["fallback_mode"] == "vibrate"
    assert set(cfg.event_mappings) >= {"player_damaged", "player_healed", "player_death", "combat_start", "quest_completed", "test_pulse"}
    # No mapping other than damage uses shock
    assert [k for k, m in cfg.event_mappings.items() if m["mode"] == "shock"] == ["player_damaged"]


def test_config_clamps_to_device_limits(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, {
        "max_intensity: 20 ": "max_intensity: 500 ",
        "max_duration_ms: 2000 ": "max_duration_ms: 99999 ",
        "session_max_shock_level: 100 ": "session_max_shock_level: 0 ",
    }))
    assert (cfg.max_intensity, cfg.max_duration_ms, cfg.session_max_shock_level) == (100, 15000, 1)


def test_config_rejects_invalid_mode(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, {"mode: beep\n    intensity: 1\n    duration_ms: 1000": "mode: zap\n    intensity: 1\n    duration_ms: 1000"}))


def test_config_requires_secret(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, {"shared_secret: change-me": "shared_secret: ''"}))


# --- protocol -----------------------------------------------------------------

def test_protocol_roundtrip_and_valid_jsonl():
    event = {"event_type": "x", "ts_ms": 1, "context": {"title": "caf\u00e9"}}
    line = build_line(event, "k")
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line)["event"] == event
    parsed = parse_line(line)
    assert parsed.format == "jsonl" and parsed.version == 1
    assert parsed.signature == sign(parsed.body, "k")


# --- PiShock HTTP client (requests is mocked; never hits the network) ---------

class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text, self.ok = status, text, 200 <= status < 300


@pytest.mark.parametrize(
    "status,text,ok",
    [(200, "Operation Succeeded.", True), (200, "Not Authorized.", False), (200, "Shocker is Paused, unable to send command.", False), (500, "", False)],
)
def test_pishock_result_interpretation(monkeypatch, status, text, ok):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(json)
        return _Resp(status, text)

    monkeypatch.setattr(pishock_http.requests, "post", fake_post)
    result = pishock_http.send_pishock_http(mode="shock", intensity=500, duration_ms=60_000, username="u", apikey="k", code="c", name="n")
    assert result.ok is ok
    assert sent["Op"] == 0 and sent["Intensity"] == 100 and sent["Duration"] == 15  # device limits enforced


def test_pishock_network_error_is_not_raised(monkeypatch):
    def boom(*a, **k):
        raise pishock_http.requests.ConnectionError("offline")

    monkeypatch.setattr(pishock_http.requests, "post", boom)
    result = pishock_http.send_pishock_http(mode="beep", intensity=1, duration_ms=300, username="u", apikey="k", code="c", name="n")
    assert result.ok is False and "offline" in result.body


# --- CLIs ---------------------------------------------------------------------

def _run(args, **kwargs):
    return subprocess.run([sys.executable, "-m", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, **kwargs)


def test_cli_consumer_processes_simulated_events(tmp_path):
    cfg = _write_cfg(tmp_path)
    outbox = tmp_path / "outbox" / "events.jsonl"
    sim = Simulator(outbox, "change-me")
    sim.emit("emitter_ready", {})
    sim.emit("player_damaged", {"damage": 100, "max_health": 400})
    sim.emit("test_pulse", {})
    proc = _run(["middleware.file_ingest", "--config", str(cfg), "--outbox", str(outbox), "--from-start", "--duration", "1.5"])
    assert proc.returncode == 0, proc.stderr
    log = proc.stderr
    assert "[SIMULATED] vibrate intensity=20 duration_ms=400 (event=player_damaged)" in log
    # Written in the same instant: the global 500 ms gap throttles the second action.
    assert "skip reason=global_cooldown event_type=test_pulse" in log
    assert "[LIVE]" not in log
    status = (tmp_path / "outbox" / "consumer_status.txt").read_text(encoding="utf-8")
    assert "state=stopped" in status and "sent=1" in status


def test_cli_simulator_writes_verifiable_lines(tmp_path):
    cfg = _write_cfg(tmp_path)
    outbox = tmp_path / "events.jsonl"
    proc = _run(["middleware.simulate", "--config", str(cfg), "--outbox", str(outbox), "--event", "player_damaged", "--damage", "50", "--max-health", "400", "--armed"])
    assert proc.returncode == 0, proc.stderr
    parsed = parse_line(outbox.read_text(encoding="utf-8").strip())
    assert parsed.signature == sign(parsed.body, "change-me")
    event = json.loads(parsed.body)
    assert event["armed"] is True and event["context"]["damage"] == 50


def test_cli_live_refused_when_config_is_dry_run(tmp_path):
    proc = _run(["middleware.file_ingest", "--config", str(_write_cfg(tmp_path)), "--outbox", str(tmp_path / "e.jsonl"), "--live", "--yes", "--duration", "0.2"])
    assert proc.returncode == 2
    assert "requires dry_run: false" in proc.stderr


def test_cli_live_refused_without_confirmation(tmp_path):
    cfg = _write_cfg(tmp_path, {"dry_run: true ": "dry_run: false "})
    proc = _run(["middleware.file_ingest", "--config", str(cfg), "--outbox", str(tmp_path / "e.jsonl"), "--live", "--duration", "0.2"], stdin=subprocess.DEVNULL)
    assert proc.returncode == 2
    assert "LIVE HARDWARE OUTPUT REQUESTED" in proc.stdout
    assert "live mode not confirmed" in proc.stderr or "refusing live mode" in proc.stdout
    assert "Traceback" not in proc.stderr


def test_cli_live_refused_with_placeholder_credentials(tmp_path):
    cfg = _write_cfg(tmp_path, {"dry_run: true ": "dry_run: false "})
    proc = _run(["middleware.file_ingest", "--config", str(cfg), "--outbox", str(tmp_path / "e.jsonl"), "--live", "--yes", "--duration", "0.2"])
    assert proc.returncode == 2
    assert "credentials are not configured" in proc.stderr


def test_cli_dry_run_false_without_live_flag_still_simulates(tmp_path):
    cfg = _write_cfg(tmp_path, {"dry_run: true ": "dry_run: false "})
    proc = _run(["middleware.file_ingest", "--config", str(cfg), "--outbox", str(tmp_path / "e.jsonl"), "--duration", "0.2"])
    assert proc.returncode == 0
    assert "output is SIMULATED" in proc.stderr


def test_estop_cli(tmp_path):
    stop = tmp_path / "ESTOP"
    assert safety.main(["--estop-file", str(stop), "--status"]) == 0
    assert safety.main(["--estop-file", str(stop)]) == 0
    assert stop.exists()
    assert safety.main(["--estop-file", str(stop), "--status"]) == 1
    assert safety.main(["--estop-file", str(stop), "--clear"]) == 0
    assert not stop.exists()


# --- setup wizard -------------------------------------------------------------

def test_setup_wizard_output_loads(tmp_path, monkeypatch):
    answers = iter([
        "user", "api:key#with-yaml-chars", "SHARE123",
        "",  # generate secret
        "C:/Games/Cyberpunk 2077/bin/x64/plugins/cyber_engine_tweaks/mods/pishock_emitter/outbox/events.jsonl",
        "", "", "", "", "", "",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    out = setup_wizard.run_wizard(str(tmp_path / "config.local.yaml"))
    cfg = load_config(out)
    assert cfg.pishock.apikey == "api:key#with-yaml-chars"
    assert len(cfg.shared_secret) == 32
    assert cfg.dry_run is True and cfg.allow_shock is False
    assert cfg.event_mappings["player_damaged"]["mode"] == "shock"  # not overwritten by a duplicate key
    assert cfg.ingest.outbox_path.endswith("events.jsonl") and " " in cfg.ingest.outbox_path


# --- mod installer ------------------------------------------------------------

def test_install_mod_copies_and_configures(tmp_path):
    game = tmp_path / "Cyberpunk 2077"
    (game / install_mod.CET_MODS_SUBDIR).mkdir(parents=True)
    target = install_mod.install(game, "s3cret")
    assert (target / "init.lua").exists() and (target / "lib" / "events.lua").exists()
    assert (target / "outbox").is_dir()
    cfg = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert cfg["shared_secret"] == "s3cret" and cfg["outbox_path"] == "outbox/events.jsonl"

    cfg["sample_interval_s"] = 0.5  # user customisation survives reinstall
    (target / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    install_mod.install(game, "new-secret")
    cfg = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert cfg["sample_interval_s"] == 0.5 and cfg["shared_secret"] == "new-secret"


def test_install_mod_requires_cet(tmp_path):
    with pytest.raises(FileNotFoundError, match="Cyber Engine Tweaks"):
        install_mod.install(tmp_path, "x")


def test_install_mod_cli_reads_secret_from_config(tmp_path):
    game = tmp_path / "game"
    (game / install_mod.CET_MODS_SUBDIR).mkdir(parents=True)
    assert install_mod.main(["--game-dir", str(game), "--config", str(EXAMPLE)]) == 0
    cfg = json.loads((game / install_mod.CET_MODS_SUBDIR / "pishock_emitter" / "config.json").read_text(encoding="utf-8"))
    assert cfg["shared_secret"] == "change-me"


def test_repo_mod_ships_outbox_dir():
    # CET cannot create directories, so the folder must be part of the mod.
    assert (MOD_SOURCE / "outbox").is_dir()

