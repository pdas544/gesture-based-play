"""Wake-gated voice assistant orchestration.

Ties together the audio loop, wake detection, the idle/awake session, spoken
greeting, and the media controller. Commands are ignored until the wake word is
heard (unless wake mode is disabled), and input is muted while the greeting is
playing so the assistant does not trigger itself.
"""

from __future__ import annotations

import logging

from .announce import Announcer, NullAnnouncer
from .config import Config
from .controller import MediaController
from .voice import EngineFactory, StreamFactory, VoiceCommandRecognizer
from .wake import WakeDetector, WakePhraseMatcher, WakeSession

logger = logging.getLogger(__name__)

CLOSE_PHRASES: tuple[str, ...] = (
    "goodbye",
    "good bye",
    "stop listening",
    "that's all",
    "thats all",
    "never mind",
    "nevermind",
)


class VoiceAssistant:
    """Listen for a wake word, then run gated media commands."""

    def __init__(
        self,
        config: Config,
        controller: MediaController,
        *,
        engine_factory: EngineFactory,
        stream_factory: StreamFactory,
        wake_enabled: bool | None = None,
        wake_detector: WakeDetector | None = None,
        wake_matcher: WakePhraseMatcher | None = None,
        announcer: Announcer | None = None,
        session: WakeSession | None = None,
    ) -> None:
        self._config = config
        self._controller = controller
        self._wake_enabled = config.wake_enabled if wake_enabled is None else wake_enabled
        self._wake_detector = wake_detector
        self._wake_matcher = wake_matcher or WakePhraseMatcher(config.wake_phrases)
        self._announcer = announcer if announcer is not None else NullAnnouncer()
        self._session = session or WakeSession(timeout=config.session_timeout_seconds)
        self._close_matcher = WakePhraseMatcher(CLOSE_PHRASES)
        self._recognizer = VoiceCommandRecognizer(
            config,
            self.on_transcript,
            on_frame=self.on_frame,
            engine_factory=engine_factory,
            stream_factory=stream_factory,
        )

    @property
    def recognizer(self) -> VoiceCommandRecognizer:
        return self._recognizer

    @property
    def session(self) -> WakeSession:
        return self._session

    @property
    def wake_description(self) -> str:
        if not self._wake_enabled:
            return "disabled (commands accepted continuously)"
        if self._wake_detector is not None:
            return f"openWakeWord ({', '.join(self._wake_detector.model_names)})"
        return f"Vosk ({', '.join(self._wake_matcher.phrases)})"

    def start(self) -> bool:
        logger.info("Wake word: %s", self.wake_description)
        return self._recognizer.start()

    def stop(self) -> None:
        self._announcer.stop()
        self._recognizer.stop()

    def on_frame(self, frame: bytes) -> None:
        """Feed an audio block to the frame-based wake detector."""
        if not self._wake_enabled or self._wake_detector is None:
            return
        if self._is_muted():
            return
        if self._session.is_awake:
            return
        if self._wake_detector.process(frame):
            self._wake()

    def on_transcript(self, text: str, is_partial: bool) -> None:
        """Handle a Vosk transcription, gated by the wake session."""
        if not text or self._is_muted():
            return

        if not self._wake_enabled:
            if self._controller.handle_phrase(text, is_partial):
                self._session.extend()
            return

        if self._session.is_awake:
            if self._close_matcher.matches(text):
                logger.info("Session closed by voice.")
                self._session.sleep()
                return
            if self._controller.handle_phrase(text, is_partial):
                self._session.extend()
            return

        # Idle with Vosk wake-word fallback (no frame-based detector).
        if self._wake_detector is None and self._wake_matcher.matches(text):
            self._wake()

    def _is_muted(self) -> bool:
        return self._session.is_muted or self._announcer.is_speaking

    def _wake(self) -> None:
        if self._announcer.is_speaking:
            return
        if not self._session.wake():
            return
        logger.info("Wake word detected.")
        self._announcer.say(self._config.greeting)
        self._session.mute(self._config.tts_cooldown_seconds)
