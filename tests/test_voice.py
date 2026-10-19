from __future__ import annotations

import threading

from gesture_media_control.config import Config
from gesture_media_control.speech import Recognition
from gesture_media_control.voice import VoiceCommandRecognizer


class FakeStream:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self, result=None) -> None:
        self.calls: list[bytes] = []
        self.finalized = False
        self._result = result if result is not None else [Recognition("play", False)]

    def ingest(self, frame: bytes) -> list[Recognition]:
        self.calls.append(frame)
        return list(self._result)

    def finalize(self) -> list[Recognition]:
        self.finalized = True
        return []


def _recognizer(config, on_phrase, engine, stream) -> VoiceCommandRecognizer:
    return VoiceCommandRecognizer(
        config,
        on_phrase,
        engine_factory=lambda: engine,
        stream_factory=lambda _recognizer: stream,
    )


def test_start_fails_when_model_directory_missing(tmp_path) -> None:
    config = Config(model_path=tmp_path / "does-not-exist")
    recognizer = _recognizer(config, lambda *_: None, FakeEngine(), FakeStream())

    assert recognizer.start() is False


def test_start_reports_missing_dependencies(tmp_path) -> None:
    def factory():
        raise ImportError("No module named 'vosk'")

    recognizer = VoiceCommandRecognizer(
        Config(model_path=tmp_path),
        lambda *_: None,
        engine_factory=factory,
        stream_factory=lambda _recognizer: FakeStream(),
    )

    assert recognizer.start() is False


def test_stream_is_started_and_closed(tmp_path) -> None:
    stream = FakeStream()
    recognizer = _recognizer(Config(model_path=tmp_path), lambda *_: None, FakeEngine(), stream)

    assert recognizer.start() is True
    recognizer.stop()

    assert stream.started is True
    assert stream.stopped is True
    assert stream.closed is True


def test_audio_frames_are_forwarded_as_phrases(tmp_path) -> None:
    received: list[tuple[str, bool]] = []
    received_event = threading.Event()

    def on_phrase(text: str, is_partial: bool) -> None:
        received.append((text, is_partial))
        received_event.set()

    engine = FakeEngine([Recognition("play", False)])
    recognizer = _recognizer(Config(model_path=tmp_path), on_phrase, engine, FakeStream())

    recognizer.start()
    try:
        recognizer.audio_callback(b"frame", 0, None, None)
        assert received_event.wait(timeout=3.0)
    finally:
        recognizer.stop()

    assert received == [("play", False)]
    assert engine.calls == [b"frame"]


def test_engine_is_finalized_on_stop(tmp_path) -> None:
    engine = FakeEngine()
    recognizer = _recognizer(Config(model_path=tmp_path), lambda *_: None, engine, FakeStream())

    recognizer.start()
    recognizer.stop()

    assert engine.finalized is True


def test_frames_are_forwarded_to_the_wake_callback(tmp_path) -> None:
    frames: list[bytes] = []
    frame_event = threading.Event()

    def on_frame(frame: bytes) -> None:
        frames.append(frame)
        frame_event.set()

    recognizer = VoiceCommandRecognizer(
        Config(model_path=tmp_path),
        lambda *_: None,
        on_frame=on_frame,
        engine_factory=lambda: FakeEngine([]),
        stream_factory=lambda _recognizer: FakeStream(),
    )

    recognizer.start()
    try:
        recognizer.audio_callback(b"frame", 0, None, None)
        assert frame_event.wait(timeout=3.0)
    finally:
        recognizer.stop()

    assert frames == [b"frame"]
