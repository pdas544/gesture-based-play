"""Dependency wiring for the application.

All third-party and OS integrations are constructed here and injected into the
core objects, keeping the rest of the package free of hard-wired dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .announce import NullAnnouncer, SpeechDispatcherAnnouncer
from .assistant import VoiceAssistant
from .config import Config
from .controller import MediaController
from .focus import FocusDetector, SystemFocusDetector
from .intents import IntentMatcher
from .players import PlayerBackend, PlayerctlBackend, PlayerResolver
from .state import StateStore
from .voice import (
    VoiceCommandRecognizer,
    default_engine_factory,
    default_stream_factory,
)
from .volume import VolumeBackend, build_volume_backend
from .wake import OpenWakeWordDetector, WakePhraseMatcher

logger = logging.getLogger(__name__)


@dataclass
class Application:
    """Fully wired application graph."""

    config: Config
    backend: PlayerBackend
    resolver: PlayerResolver
    matcher: IntentMatcher
    state: StateStore
    assistant: VoiceAssistant
    controller: MediaController
    volume_backend: VolumeBackend

    @property
    def recognizer(self) -> VoiceCommandRecognizer:
        """Backwards-compatible access to the underlying recognizer."""
        return self.assistant.recognizer

    def target_label(self) -> str:
        return (
            self.resolver.runtime_override
            or self.config.preferred_player
            or self.resolver.last_target
            or "auto"
        )

    def status_line(self) -> str:
        snapshot = self.state.snapshot()
        last_intent = snapshot.last_intent.value if snapshot.last_intent else "—"
        return (
            f"State: {snapshot.current_state} | "
            f"Last command: {last_intent} | "
            f"Target: {self.target_label()}"
        )


def _build_wake(config: Config, command_phrases: list[str]):
    """Return (detector, matcher, engine_phrases) for the configured wake mode."""
    if not config.wake_enabled:
        return None, None, command_phrases

    wake_phrases = config.wake_phrases or ("hey lenovo", "ok lenovo")
    wake_matcher = WakePhraseMatcher(wake_phrases)
    engine = config.wake_engine.strip().lower()

    if engine in ("auto", "openwakeword"):
        try:
            detector = OpenWakeWordDetector(
                model_names=config.wake_models,
                threshold=config.wake_threshold,
            )
            logger.info("Wake word engine: openWakeWord (%s)", ", ".join(config.wake_models))
            return detector, None, command_phrases
        except Exception as error:  # missing package, model download failure, ...
            logger.warning(
                "openWakeWord unavailable (%s); falling back to Vosk wake phrases.", error
            )

    logger.info("Wake word engine: Vosk (%s)", ", ".join(wake_phrases))
    return None, wake_matcher, command_phrases + list(wake_phrases)


def build_application(
    config: Config,
    *,
    backend: PlayerBackend | None = None,
    focus_detector: FocusDetector | None = None,
) -> Application:
    """Construct the application graph for ``config``."""
    backend = backend if backend is not None else PlayerctlBackend()

    if focus_detector is None and config.prefer_focused_player:
        focus_detector = SystemFocusDetector()

    resolver = PlayerResolver(
        backend,
        focus_detector=focus_detector,
        preferred_player=config.preferred_player,
        prefer_focused_player=config.prefer_focused_player,
    )
    matcher = IntentMatcher()
    state = StateStore()
    volume_backend = build_volume_backend(
        config.volume_backend,
        backend=backend,
        resolver=resolver,
        step_percent=config.volume_step_percent,
    )
    controller = MediaController(
        backend,
        resolver,
        matcher,
        state,
        volume_backend=volume_backend,
        guard_seconds=config.transition_guard_seconds,
    )

    wake_detector, wake_matcher, engine_phrases = _build_wake(config, matcher.phrases())
    announcer = (
        SpeechDispatcherAnnouncer(command=config.tts_command)
        if config.wake_enabled
        else NullAnnouncer()
    )
    assistant = VoiceAssistant(
        config,
        controller,
        engine_factory=default_engine_factory(config, engine_phrases),
        stream_factory=default_stream_factory(config),
        wake_detector=wake_detector,
        wake_matcher=wake_matcher,
        announcer=announcer,
    )

    return Application(
        config=config,
        backend=backend,
        resolver=resolver,
        matcher=matcher,
        state=state,
        assistant=assistant,
        controller=controller,
        volume_backend=volume_backend,
    )
