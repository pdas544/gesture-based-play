from __future__ import annotations

import json

from gesture_media_control.speech import Recognition, VoskEngine


class FakeRecognizer:
    def __init__(
        self,
        accept: list[bool],
        results: list[str] | None = None,
        partials: list[str] | None = None,
        final: str = '{"text": ""}',
    ) -> None:
        self._accept = list(accept)
        self._results = list(results or [])
        self._partials = list(partials or [])
        self._final = final
        self.accept_calls = 0
        self.grammar: str | None = None

    def AcceptWaveform(self, _data) -> bool:  # noqa: N802 - Vosk API name
        self.accept_calls += 1
        return self._accept.pop(0)

    def Result(self) -> str:  # noqa: N802
        return self._results.pop(0)

    def PartialResult(self) -> str:  # noqa: N802
        return self._partials.pop(0)

    def FinalResult(self) -> str:  # noqa: N802
        return self._final

    def SetGrammar(self, grammar: str) -> None:  # noqa: N802
        self.grammar = grammar


def test_ingest_final_returns_final_recognition() -> None:
    fake = FakeRecognizer(accept=[True], results=['{"text": "play music"}'])
    engine = VoskEngine(fake)

    assert engine.ingest(b"frame") == [Recognition("play music", is_partial=False)]
    assert fake.accept_calls == 1


def test_ingest_partial_returns_partial_recognition() -> None:
    fake = FakeRecognizer(accept=[False], partials=['{"partial": "vol"}'])
    engine = VoskEngine(fake)

    assert engine.ingest(b"frame") == [Recognition("vol", is_partial=True)]
    assert fake.accept_calls == 1


def test_each_frame_is_fed_exactly_once() -> None:
    fake = FakeRecognizer(
        accept=[False, True], partials=['{"partial": "a"}'], results=['{"text": "b"}']
    )
    engine = VoskEngine(fake)

    engine.ingest(b"one")
    engine.ingest(b"two")

    assert fake.accept_calls == 2


def test_empty_transcription_yields_nothing() -> None:
    fake = FakeRecognizer(accept=[True], results=['{"text": ""}'])
    engine = VoskEngine(fake)

    assert engine.ingest(b"frame") == []


def test_invalid_json_is_ignored() -> None:
    fake = FakeRecognizer(accept=[True], results=["not json"])
    engine = VoskEngine(fake)

    assert engine.ingest(b"frame") == []


def test_finalize_returns_final_recognition() -> None:
    fake = FakeRecognizer(accept=[], final='{"text": "next"}')
    engine = VoskEngine(fake)

    assert engine.finalize() == [Recognition("next", is_partial=False)]


def test_set_grammar_serializes_phrases() -> None:
    fake = FakeRecognizer(accept=[])
    engine = VoskEngine(fake)

    engine.set_grammar(["play", "pause"])

    assert json.loads(fake.grammar) == ["play", "pause"]
