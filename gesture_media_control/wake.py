"""Wake-word detection and the idle/awake session state machine."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_WAKE_PHRASES: tuple[str, ...] = ("hey lenovo", "ok lenovo")


class WakeState(str, Enum):
    IDLE = "idle"
    AWAKE = "awake"


class WakeSession:
    """Track whether commands should be accepted after a wake word.

    The session opens on wake, closes after ``timeout`` seconds of inactivity,
    and is extended each time a command is accepted. Audio is ignored while the
    assistant is speaking to avoid the greeting triggering a command.
    """

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._timeout = timeout
        self._clock = clock
        self._state = WakeState.IDLE
        self._deadline = 0.0
        self._mute_until = 0.0

    @property
    def state(self) -> WakeState:
        self._expire()
        return self._state

    @property
    def is_awake(self) -> bool:
        return self.state is WakeState.AWAKE

    @property
    def is_muted(self) -> bool:
        return self._clock() < self._mute_until

    def wake(self) -> bool:
        """Open a session. Return True only on the idle -> awake transition."""
        if self.is_muted:
            return False
        self._expire()
        if self._state is WakeState.AWAKE:
            return False
        self._state = WakeState.AWAKE
        self._deadline = self._clock() + self._timeout
        return True

    def extend(self) -> None:
        """Keep the session open after a successful command."""
        if self._state is WakeState.AWAKE:
            self._deadline = self._clock() + self._timeout

    def sleep(self) -> None:
        self._state = WakeState.IDLE
        self._deadline = 0.0

    def accept_commands(self) -> bool:
        """Return True when awake and not muted."""
        self._expire()
        return self._state is WakeState.AWAKE and not self.is_muted

    def mute(self, seconds: float) -> None:
        """Ignore input for ``seconds`` (used while the greeting plays)."""
        self._mute_until = max(self._mute_until, self._clock() + seconds)

    def _expire(self) -> None:
        if self._state is WakeState.AWAKE and self._clock() >= self._deadline:
            self._state = WakeState.IDLE
            self._deadline = 0.0


class WakePhraseMatcher:
    """Word-boundary matcher for Vosk-based wake detection."""

    def __init__(self, phrases: Sequence[str] = DEFAULT_WAKE_PHRASES) -> None:
        self._phrases = [phrase.strip().lower() for phrase in phrases if phrase.strip()]
        self._patterns = [re.compile(r"\b" + re.escape(phrase) + r"\b") for phrase in self._phrases]

    @property
    def phrases(self) -> tuple[str, ...]:
        return tuple(self._phrases)

    def matches(self, text: str | None) -> bool:
        if not text:
            return False
        normalized = " ".join(text.split()).lower()
        return any(pattern.search(normalized) for pattern in self._patterns)


class WakeDetector(Protocol):
    """Detects a wake word in a raw audio block."""

    def process(self, frame: bytes) -> bool: ...


def _create_openwakeword_model(model_names: Sequence[str] = ("hey_jarvis",)):
    from openwakeword.model import Model
    from openwakeword.utils import download_models

    download_models(model_names=list(model_names))
    return Model(wakeword_models=list(model_names), inference_framework="onnx")


class OpenWakeWordDetector:
    """Wake-word detection using openWakeWord's pretrained ONNX models."""

    def __init__(
        self,
        *,
        model_names: Sequence[str] = ("hey_jarvis",),
        threshold: float = 0.5,
        model_factory: Callable[[Sequence[str]], object] | None = None,
    ) -> None:
        self._threshold = threshold
        factory = model_factory or _create_openwakeword_model
        self._model = factory(model_names)
        self._names = tuple(model_names)

    @property
    def model_names(self) -> tuple[str, ...]:
        return self._names

    def process(self, frame: bytes) -> bool:
        if not frame:
            return False

        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16)
        try:
            scores = self._model.predict(samples)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Wake-word detection failed")
            return False

        if not isinstance(scores, dict):
            return False
        return any(float(score) >= self._threshold for score in scores.values())
