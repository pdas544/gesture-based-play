from __future__ import annotations

from pathlib import Path

from gesture_media_control.assistant import VoiceAssistant
from gesture_media_control.config import Config
from gesture_media_control.wake import WakePhraseMatcher, WakeSession


class StubController:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[str, bool]] = []

    def handle_phrase(self, text: str, is_partial: bool) -> bool:
        self.calls.append((text, is_partial))
        return self.accepted


class FakeAnnouncer:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.speaking = False
        self.stopped = False

    @property
    def is_speaking(self) -> bool:
        return self.speaking

    def say(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stopped = True


class FakeDetector:
    def __init__(self, detected: bool = True) -> None:
        self.detected = detected
        self.calls: list[bytes] = []

    @property
    def model_names(self) -> tuple[str, ...]:
        return ("hey_jarvis",)

    def process(self, frame: bytes) -> bool:
        self.calls.append(frame)
        return self.detected


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _assistant(
    *,
    wake_enabled: bool = True,
    detector: FakeDetector | None = None,
    announcer: FakeAnnouncer | None = None,
    controller: StubController | None = None,
    clock: Clock | None = None,
    timeout: float = 10.0,
    greeting: str = "Hi, how can I help",
) -> tuple[VoiceAssistant, StubController, FakeAnnouncer, Clock]:
    clock = clock or Clock()
    announcer = announcer or FakeAnnouncer()
    controller = controller or StubController()
    config = Config(
        model_path=Path("model"),
        wake_enabled=wake_enabled,
        greeting=greeting,
        tts_cooldown_seconds=0.5,
        session_timeout_seconds=timeout,
    )
    assistant = VoiceAssistant(
        config,
        controller,  # type: ignore[arg-type]
        engine_factory=lambda: None,  # type: ignore[arg-type,return-value]
        stream_factory=lambda _recognizer: None,  # type: ignore[arg-type,return-value]
        wake_enabled=wake_enabled,
        wake_detector=detector,
        wake_matcher=WakePhraseMatcher(("hey lenovo", "ok lenovo")),
        announcer=announcer,
        session=WakeSession(timeout=timeout, clock=clock),
    )
    return assistant, controller, announcer, clock


def test_commands_pass_through_when_wake_disabled() -> None:
    assistant, controller, announcer, _ = _assistant(wake_enabled=False)

    assistant.on_transcript("play", False)

    assert controller.calls == [("play", False)]
    assert announcer.spoken == []


def test_wake_phrase_greets_and_opens_session() -> None:
    assistant, controller, announcer, clock = _assistant()
    clock.now = 1.0

    assistant.on_transcript("hey lenovo", False)

    assert announcer.spoken == ["Hi, how can I help"]
    assert assistant.session.is_awake is True
    assert controller.calls == []


def test_commands_run_after_wake_and_extend_session() -> None:
    assistant, controller, _, clock = _assistant()

    assistant.on_transcript("ok lenovo", False)
    clock.now = 1.0
    assistant.on_transcript("play", False)

    assert controller.calls == [("play", False)]
    assert assistant.session.is_awake is True


def test_commands_are_ignored_while_idle_with_frame_detector() -> None:
    assistant, controller, _, _ = _assistant(detector=FakeDetector())

    assistant.on_transcript("play", False)

    assert controller.calls == []
    assert assistant.session.is_awake is False


def test_frame_detector_wakes_only_when_idle() -> None:
    detector = FakeDetector(detected=True)
    assistant, _, announcer, clock = _assistant(detector=detector)

    assistant.on_frame(b"first")
    assert detector.calls == [b"first"]
    assert announcer.spoken == ["Hi, how can I help"]
    assert assistant.session.is_awake is True

    clock.now = 1.0
    assistant.on_frame(b"second")
    assert detector.calls == [b"first"]


def test_input_is_ignored_while_speaking() -> None:
    announcer = FakeAnnouncer()
    announcer.speaking = True
    assistant, controller, _, _ = _assistant(detector=FakeDetector(), announcer=announcer)

    assistant.on_frame(b"frame")
    assistant.on_transcript("hey lenovo", False)

    assert controller.calls == []
    assert announcer.spoken == []


def test_goodbye_closes_the_session() -> None:
    assistant, controller, _, clock = _assistant()

    assistant.on_transcript("hey lenovo", False)
    clock.now = 1.0
    assistant.on_transcript("goodbye", False)

    assert assistant.session.is_awake is False

    assistant.on_transcript("play", False)
    assert controller.calls == []


def test_session_expires_after_timeout() -> None:
    assistant, controller, _, clock = _assistant(detector=FakeDetector(), timeout=10.0)

    assistant.on_frame(b"wake")
    clock.now = 9.0
    assistant.on_transcript("play", False)
    assert controller.calls == [("play", False)]

    clock.now = 25.0
    assistant.on_transcript("pause", False)
    assert assistant.session.is_awake is False
    assert controller.calls == [("play", False)]


def test_non_wake_phrase_does_not_open_session() -> None:
    assistant, controller, announcer, _ = _assistant()

    assistant.on_transcript("play", False)

    assert controller.calls == []
    assert announcer.spoken == []
    assert assistant.session.is_awake is False


def test_failed_command_does_not_extend_session() -> None:
    controller = StubController(accepted=False)
    assistant, _, _, clock = _assistant(controller=controller)

    assistant.on_transcript("hey lenovo", False)
    clock.now = 1.0
    assistant.on_transcript("play", False)

    assert controller.calls == [("play", False)]
    clock.now = 12.0
    assert assistant.session.is_awake is False


def test_wake_description_reports_active_engine() -> None:
    frame_assistant, _, _, _ = _assistant(detector=FakeDetector())
    vosk_assistant, _, _, _ = _assistant()
    off_assistant, _, _, _ = _assistant(wake_enabled=False)

    assert "openWakeWord" in frame_assistant.wake_description
    assert "Vosk" in vosk_assistant.wake_description
    assert "disabled" in off_assistant.wake_description


def test_stop_stops_announcer() -> None:
    assistant, _, announcer, _ = _assistant()

    assistant.stop()

    assert announcer.stopped is True
