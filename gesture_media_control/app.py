"""Dependency wiring for the application.

All third-party and OS integrations are constructed here and injected into the
core objects, keeping the rest of the package free of hard-wired dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class Application:
    """Fully wired application graph."""

    config: Config
    backend: PlayerBackend
    resolver: PlayerResolver
    matcher: IntentMatcher
    state: StateStore
    recognizer: VoiceCommandRecognizer
    controller: MediaController

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
    controller = MediaController(
        backend,
        resolver,
        matcher,
        state,
        guard_seconds=config.transition_guard_seconds,
    )
    recognizer = VoiceCommandRecognizer(
        config,
        controller.handle_phrase,
        engine_factory=default_engine_factory(config, matcher.phrases()),
        stream_factory=default_stream_factory(config),
    )
    return Application(
        config=config,
        backend=backend,
        resolver=resolver,
        matcher=matcher,
        state=state,
        recognizer=recognizer,
        controller=controller,
    )
