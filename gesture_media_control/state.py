"""Thread-safe application state.

The recognition thread writes state while the console thread reads it, so all
access goes through a lock-guarded store rather than loose module globals.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from .intents import Intent


@dataclass
class AppState:
    """Snapshot of the mutable runtime state."""

    current_state: str = "Idle"  # Playing / Paused / Idle
    last_intent: Intent | None = None
    last_action_time: float = 0.0
    playerctl_hint_shown: bool = False


class StateStore:
    """Lock-guarded owner of :class:`AppState`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AppState()

    def snapshot(self) -> AppState:
        with self._lock:
            return replace(self._state)

    def set_current_state(self, value: str) -> None:
        with self._lock:
            self._state.current_state = value

    def should_suppress(self, intent: Intent, now: float, guard_seconds: float) -> bool:
        """True when ``intent`` repeats too soon after the previous action."""
        with self._lock:
            return (
                intent == self._state.last_intent
                and (now - self._state.last_action_time) < guard_seconds
            )

    def record_action(self, intent: Intent, timestamp: float) -> None:
        with self._lock:
            self._state.last_intent = intent
            self._state.last_action_time = timestamp

    def mark_hint_shown(self) -> bool:
        """Return True the first time it is called, False afterwards."""
        with self._lock:
            if self._state.playerctl_hint_shown:
                return False
            self._state.playerctl_hint_shown = True
            return True
