"""Application orchestration: turn a recognized phrase into a media action."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .intents import Intent, IntentMatcher
from .players import PlayerBackend, PlayerResolver
from .state import StateStore
from .volume import VOLUME_INTENTS, VolumeBackend

logger = logging.getLogger(__name__)


class MediaController:
    """Match phrases, resolve a target player, execute, and update state."""

    def __init__(
        self,
        backend: PlayerBackend,
        resolver: PlayerResolver,
        matcher: IntentMatcher,
        state: StateStore,
        *,
        volume_backend: VolumeBackend | None = None,
        guard_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._resolver = resolver
        self._matcher = matcher
        self._state = state
        self._volume_backend = volume_backend
        self._guard_seconds = guard_seconds
        self._clock = clock

    def handle_phrase(self, text: str, is_partial: bool = False) -> bool:
        """Handle a transcription; return True when a command was executed."""
        intent = self._matcher.match(text)
        if intent is None:
            return False
        return self.handle_intent(intent, text=text, is_partial=is_partial)

    def handle_intent(self, intent: Intent, *, text: str = "", is_partial: bool = False) -> bool:
        """Execute ``intent`` unless it duplicates a recent command."""
        now = self._clock()
        if self._state.should_suppress(intent, now, self._guard_seconds):
            return False

        if intent in VOLUME_INTENTS and self._volume_backend is not None:
            return self._change_volume(intent, now, text, is_partial)

        if not self._backend.is_available():
            logger.warning("Cannot send %s: playerctl is not installed.", intent.value)
            if self._state.mark_hint_shown():
                logger.info("Install playerctl for Linux media control: sudo apt install playerctl")
            return False

        target = self._resolver.resolve(intent)
        if not target:
            logger.warning("No unambiguous media player found for %s.", intent.value)
            logger.info("Pause other players or start playback in the player you want to control.")
            return False

        if not self._skip_supported(target, intent):
            return False

        result = self._backend.execute(target, intent)
        if not result.ok:
            logger.error(
                "playerctl failed for %s on %s: %s",
                intent.value,
                target,
                result.stderr.strip(),
            )
            return False

        self._resolver.record_target(target)
        self._state.record_action(intent, now)
        if intent == Intent.PLAY:
            self._state.set_current_state("Playing")
        elif intent == Intent.PAUSE:
            self._state.set_current_state("Paused")

        if text:
            logger.info(
                'Recognized "%s" (%s) -> %s on %s',
                text,
                "partial" if is_partial else "final",
                intent.value,
                target,
            )
        else:
            logger.info("Executed %s on %s", intent.value, target)
        return True

    def _change_volume(self, intent: Intent, now: float, text: str, is_partial: bool) -> bool:
        assert self._volume_backend is not None
        result = self._volume_backend.change(intent)
        if not result.ok:
            logger.error(
                "Volume change failed for %s: %s",
                intent.value,
                result.stderr.strip() or f"rc={result.returncode}",
            )
            return False

        self._state.record_action(intent, now)
        if text:
            logger.info(
                'Recognized "%s" (%s) -> %s (system volume)',
                text,
                "partial" if is_partial else "final",
                intent.value,
            )
        else:
            logger.info("Executed %s (system volume)", intent.value)
        return True

    def _skip_supported(self, target: str, intent: Intent) -> bool:
        """Warn and return False when the player says it cannot skip."""
        lookup = getattr(self._backend, "get_capabilities", None)
        if lookup is None:
            return True
        capabilities = lookup(target)
        if capabilities is None:
            return True

        if intent == Intent.NEXT and capabilities.can_go_next is False:
            logger.warning("%s reports this track cannot skip forward (CanGoNext=false).", target)
            return False
        if intent == Intent.PREVIOUS and capabilities.can_go_previous is False:
            logger.warning("%s reports this track cannot skip back (CanGoPrevious=false).", target)
            return False
        return True
