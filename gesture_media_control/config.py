"""Runtime configuration.

All tunables live here instead of being scattered module-level globals. Values
can be overridden through ``VMC_*`` environment variables, which keeps the
application testable and avoids hard-coded machine specifics.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_DIRNAME = "vosk-model-small-en-us-0.15"
ENV_PREFIX = "VMC_"


def _default_model_path() -> Path:
    """Resolve the default Vosk model directory.

    Precedence: ``VMC_MODEL_PATH`` -> ``<repo>/models/<name>`` -> ``./models/<name>``.
    """
    override = os.environ.get(f"{ENV_PREFIX}MODEL_PATH")
    if override:
        return Path(override).expanduser()

    repo_root = Path(__file__).resolve().parent.parent
    candidate = repo_root / "models" / DEFAULT_MODEL_DIRNAME
    if candidate.is_dir():
        return candidate

    return Path.cwd() / "models" / DEFAULT_MODEL_DIRNAME


def _env_str(name: str, default: str | None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from error


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}") from error


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""

    model_path: Path
    sample_rate: int = 16000
    channels: int = 1
    audio_block_size: int = 800  # ~50 ms at 16 kHz
    transition_guard_seconds: float = 0.5
    preferred_player: str | None = None
    prefer_focused_player: bool = True
    volume_backend: str = "auto"  # auto | system | mpris
    volume_step_percent: int = 5
    wake_enabled: bool = True
    wake_engine: str = "auto"  # auto | openwakeword | vosk
    wake_models: tuple[str, ...] = ("hey_jarvis",)
    wake_threshold: float = 0.5
    wake_phrases: tuple[str, ...] = ("hey lenovo", "ok lenovo")
    session_timeout_seconds: float = 10.0
    greeting: str = "Hi, how can I help"
    tts_command: str = "spd-say"
    tts_cooldown_seconds: float = 0.5

    @classmethod
    def from_env(cls) -> Config:
        """Build a configuration from ``VMC_*`` environment variables."""
        return cls(
            model_path=_default_model_path(),
            sample_rate=_env_int(f"{ENV_PREFIX}SAMPLE_RATE", 16000),
            channels=_env_int(f"{ENV_PREFIX}CHANNELS", 1),
            audio_block_size=_env_int(f"{ENV_PREFIX}AUDIO_BLOCK_SIZE", 800),
            transition_guard_seconds=_env_float(f"{ENV_PREFIX}TRANSITION_GUARD", 0.5),
            preferred_player=_env_str(f"{ENV_PREFIX}PREFERRED_PLAYER", None),
            prefer_focused_player=_env_bool(f"{ENV_PREFIX}PREFER_FOCUSED_PLAYER", True),
            volume_backend=_env_str(f"{ENV_PREFIX}VOLUME_BACKEND", "auto") or "auto",
            volume_step_percent=_env_int(f"{ENV_PREFIX}VOLUME_STEP_PERCENT", 5),
            wake_enabled=_env_bool(f"{ENV_PREFIX}WAKE_ENABLED", True),
            wake_engine=_env_str(f"{ENV_PREFIX}WAKE_ENGINE", "auto") or "auto",
            wake_models=_env_list(f"{ENV_PREFIX}WAKE_MODELS", ("hey_jarvis",)),
            wake_threshold=_env_float(f"{ENV_PREFIX}WAKE_THRESHOLD", 0.5),
            wake_phrases=_env_list(f"{ENV_PREFIX}WAKE_PHRASES", ("hey lenovo", "ok lenovo")),
            session_timeout_seconds=_env_float(f"{ENV_PREFIX}SESSION_TIMEOUT", 10.0),
            greeting=_env_str(f"{ENV_PREFIX}GREETING", "Hi, how can I help")
            or "Hi, how can I help",
            tts_command=_env_str(f"{ENV_PREFIX}TTS_COMMAND", "spd-say") or "spd-say",
            tts_cooldown_seconds=_env_float(f"{ENV_PREFIX}TTS_COOLDOWN", 0.5),
        )
