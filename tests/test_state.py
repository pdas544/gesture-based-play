from __future__ import annotations

from gesture_media_control.intents import Intent
from gesture_media_control.state import StateStore


def test_initial_snapshot_is_idle() -> None:
    snapshot = StateStore().snapshot()
    assert snapshot.current_state == "Idle"
    assert snapshot.last_intent is None


def test_suppresses_duplicate_within_guard() -> None:
    state = StateStore()
    state.record_action(Intent.PLAY, 10.0)

    assert state.should_suppress(Intent.PLAY, 10.2, guard_seconds=0.5) is True


def test_does_not_suppress_after_guard() -> None:
    state = StateStore()
    state.record_action(Intent.PLAY, 10.0)

    assert state.should_suppress(Intent.PLAY, 10.6, guard_seconds=0.5) is False


def test_does_not_suppress_different_intent() -> None:
    state = StateStore()
    state.record_action(Intent.PLAY, 10.0)

    assert state.should_suppress(Intent.PAUSE, 10.1, guard_seconds=0.5) is False


def test_snapshot_is_a_copy() -> None:
    state = StateStore()
    snapshot = state.snapshot()
    state.set_current_state("Playing")

    assert snapshot.current_state == "Idle"
    assert state.snapshot().current_state == "Playing"


def test_mark_hint_shown_only_true_once() -> None:
    state = StateStore()

    assert state.mark_hint_shown() is True
    assert state.mark_hint_shown() is False
