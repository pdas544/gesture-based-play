"""Speech-to-text engine wrapper.

``VoskEngine`` adapts Vosk's ``KaldiRecognizer`` behind a tiny ``SpeechEngine``
interface. Audio blocks are processed exactly once, and each block yields either
a partial or a final transcription, which fixes the previous double-feed bug.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Recognition:
    """A single partial or final transcription."""

    text: str
    is_partial: bool


class SpeechEngine(Protocol):
    """Consumes audio frames and emits transcriptions."""

    def ingest(self, frame: bytes) -> list[Recognition]: ...

    def finalize(self) -> list[Recognition]: ...


class VoskEngine:
    """Thin adapter over a Vosk ``KaldiRecognizer``."""

    def __init__(self, recognizer: Any, *, dumps=json.dumps, loads=json.loads) -> None:
        self._recognizer = recognizer
        self._dumps = dumps
        self._loads = loads

    @classmethod
    def create(
        cls,
        model_path: str,
        phrases: Sequence[str] = (),
        sample_rate: int = 16000,
        *,
        log_level: int = -1,
    ) -> VoskEngine:
        """Load a Vosk model from ``model_path`` and build an engine."""
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(log_level)
        model = Model(str(model_path))
        recognizer = KaldiRecognizer(model, sample_rate)
        engine = cls(recognizer)
        if phrases:
            engine.set_grammar(phrases)
        return engine

    def set_grammar(self, phrases: Sequence[str]) -> None:
        """Constrain recognition to the given phrases."""
        self._recognizer.SetGrammar(self._dumps(list(phrases)))

    def ingest(self, frame: bytes) -> list[Recognition]:
        """Feed one audio block; return at most one transcription."""
        if self._recognizer.AcceptWaveform(frame):
            text = self._parse(self._recognizer.Result(), "text")
            return [Recognition(text, is_partial=False)] if text else []
        text = self._parse(self._recognizer.PartialResult(), "partial")
        return [Recognition(text, is_partial=True)] if text else []

    def finalize(self) -> list[Recognition]:
        """Flush pending audio and return any final transcription."""
        text = self._parse(self._recognizer.FinalResult(), "text")
        return [Recognition(text, is_partial=False)] if text else []

    def _parse(self, raw: str, key: str) -> str:
        try:
            payload = self._loads(raw)
        except (TypeError, ValueError):
            return ""
        value = payload.get(key, "") if isinstance(payload, dict) else ""
        return str(value).strip().lower()
