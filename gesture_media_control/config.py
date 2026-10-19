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
        )
