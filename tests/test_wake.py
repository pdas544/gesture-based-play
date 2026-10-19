from __future__ import annotations

import logging

from gesture_media_control.wake import (
    OpenWakeWordDetector,
    WakePhraseMatcher,
    WakeSession,
    WakeState,
)


class Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_session_starts_idle() -> None:
    session = WakeSession(clock=Clock())
    assert session.state is WakeState.IDLE
    assert session.accept_commands() is False


def test_wake_opens_session() -> None:
    clock = Clock(10.0)
    session = WakeSession(timeout=5.0, clock=clock)

    assert session.wake() is True
    assert session.is_awake is True
    assert session.accept_commands() is True


def test_wake_twice_does_not_retrigger() -> None:
    session = WakeSession(clock=Clock())
    assert session.wake() is True
    assert session.wake() is False


def test_session_expires_after_timeout() -> None:
    clock = Clock(10.0)
    session = WakeSession(timeout=5.0, clock=clock)
    session.wake()

    clock.now = 15.0
    assert session.state is WakeState.IDLE
    assert session.accept_commands() is False


def test_extend_keeps_session_open() -> None:
    clock = Clock(10.0)
    session = WakeSession(timeout=5.0, clock=clock)
    session.wake()

    clock.now = 14.0
    session.extend()
    clock.now = 18.0
    assert session.accept_commands() is True

    clock.now = 20.0
    assert session.accept_commands() is False


def test_sleep_closes_immediately() -> None:
    session = WakeSession(clock=Clock())
    session.wake()
    session.sleep()
    assert session.state is WakeState.IDLE


def test_mute_blocks_wake_and_commands() -> None:
    clock = Clock(0.0)
    session = WakeSession(timeout=10.0, clock=clock)
    session.wake()
    session.mute(2.0)

    assert session.is_muted is True
    assert session.accept_commands() is False
    assert session.wake() is False

    clock.now = 2.5
    assert session.is_muted is False
    assert session.accept_commands() is True


class FakeModel:
    def __init__(self, scores=None, error: Exception | None = None) -> None:
        self.scores = scores or {}
        self.error = error
        self.frames: list[object] = []

    def predict(self, samples):
        self.frames.append(samples)
        if self.error is not None:
            raise self.error
        return self.scores


def test_openwakeword_detects_above_threshold() -> None:
    model = FakeModel({"hey_jarvis": 0.9})
    detector = OpenWakeWordDetector(model_factory=lambda _names: model)

    assert detector.process(b"\x00\x00" * 10) is True
    assert model.frames


def test_openwakeword_ignores_below_threshold() -> None:
    model = FakeModel({"hey_jarvis": 0.1})
    detector = OpenWakeWordDetector(threshold=0.5, model_factory=lambda _names: model)

    assert detector.process(b"\x00\x00" * 10) is False


def test_openwakeword_ignores_empty_frame() -> None:
    model = FakeModel({"hey_jarvis": 0.9})
    detector = OpenWakeWordDetector(model_factory=lambda _names: model)

    assert detector.process(b"") is False
    assert model.frames == []


def test_openwakeword_handles_model_errors(caplog) -> None:
    model = FakeModel(error=RuntimeError("boom"))
    detector = OpenWakeWordDetector(model_factory=lambda _names: model)

    with caplog.at_level(logging.ERROR):
        assert detector.process(b"\x00\x00" * 10) is False

    assert any("Wake-word detection failed" in record.message for record in caplog.records)


def test_openwakeword_exposes_model_names() -> None:
    detector = OpenWakeWordDetector(
        model_names=("hey_jarvis",), model_factory=lambda _names: FakeModel()
    )
    assert detector.model_names == ("hey_jarvis",)


def test_wake_phrase_matcher() -> None:
    matcher = WakePhraseMatcher(["hey lenovo", "ok lenovo"])

    assert matcher.matches("Hey Lenovo") is True
    assert matcher.matches("okay lenovo") is False
    assert matcher.matches("hey lenovoesque") is False
    assert matcher.matches("") is False
    assert matcher.phrases == ("hey lenovo", "ok lenovo")
