from __future__ import annotations

import pytest
from gesture_media_control.config import Config


def test_from_env_applies_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VMC_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("VMC_SAMPLE_RATE", "8000")
    monkeypatch.setenv("VMC_AUDIO_BLOCK_SIZE", "1234")
    monkeypatch.setenv("VMC_TRANSITION_GUARD", "1.5")
    monkeypatch.setenv("VMC_PREFERRED_PLAYER", "spotify")
    monkeypatch.setenv("VMC_PREFER_FOCUSED_PLAYER", "false")

    config = Config.from_env()

    assert config.model_path == tmp_path
    assert config.sample_rate == 8000
    assert config.audio_block_size == 1234
    assert config.transition_guard_seconds == 1.5
    assert config.preferred_player == "spotify"
    assert config.prefer_focused_player is False


def test_from_env_defaults(monkeypatch) -> None:
    for name in (
        "VMC_MODEL_PATH",
        "VMC_SAMPLE_RATE",
        "VMC_AUDIO_BLOCK_SIZE",
        "VMC_TRANSITION_GUARD",
        "VMC_PREFERRED_PLAYER",
        "VMC_PREFER_FOCUSED_PLAYER",
    ):
        monkeypatch.delenv(name, raising=False)

    config = Config.from_env()

    assert config.sample_rate == 16000
    assert config.audio_block_size == 800
    assert config.transition_guard_seconds == 0.5
    assert config.preferred_player is None
    assert config.prefer_focused_player is True
    assert config.model_path.name == "vosk-model-small-en-us-0.15"


def test_invalid_integer_override_raises(monkeypatch) -> None:
    monkeypatch.setenv("VMC_SAMPLE_RATE", "not-a-number")

    with pytest.raises(ValueError, match="must be an integer"):
        Config.from_env()
