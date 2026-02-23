"""Tests for default safety-oriented mapping templates."""

from pathlib import Path


def _example_config_text() -> str:
    return Path("middleware/config.example.yaml").read_text(encoding="utf-8")


def test_example_config_uses_damage_only_for_shock():
    text = _example_config_text()

    assert "player_damaged:\n    mode: shock" in text
    assert "player_healed:\n    mode: shock" not in text
    assert "quest_completed:\n    mode: shock" not in text
    assert "combat_start:\n    mode: shock" not in text


def test_example_config_positive_events_use_vibrate():
    text = _example_config_text()

    assert "player_healed:\n    mode: vibrate" in text
    assert "quest_completed:\n    mode: vibrate" in text
