from __future__ import annotations

import logging

from gesture_media_control.controller import MediaController
from gesture_media_control.intents import Intent, IntentMatcher
from gesture_media_control.players import (
    CommandResult,
    PlayerCapabilities,
    PlayerResolver,
)
from gesture_media_control.state import StateStore


class FakeBackend:
    def __init__(self, players=(), available=True, result=None, capabilities=None) -> None:
        self._players = list(players)
        self.available = available
        self.result = result or CommandResult(0)
        self.capabilities = capabilities
        self.executed: list[tuple[str, Intent]] = []

    def is_available(self) -> bool:
        return self.available

    def list_players(self) -> list[str]:
        return list(self._players)

    def get_status(self, _player: str) -> str | None:
        return "Playing"

    def get_capabilities(self, _player: str) -> PlayerCapabilities | None:
        return self.capabilities

    def execute(self, player: str, intent: Intent) -> CommandResult:
        self.executed.append((player, intent))
        return self.result


class Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def make_controller(backend: FakeBackend, clock: Clock | None = None) -> MediaController:
    return MediaController(
        backend,
        PlayerResolver(backend),
        IntentMatcher(),
        StateStore(),
        guard_seconds=0.5,
        clock=clock or Clock(),
    )


def test_handle_phrase_executes_matching_command() -> None:
    backend = FakeBackend(["spotify"])
    controller = make_controller(backend)

    assert controller.handle_phrase("please play") is True
    assert backend.executed == [("spotify", Intent.PLAY)]
    assert controller._state.snapshot().current_state == "Playing"


def test_pause_sets_paused_state() -> None:
    backend = FakeBackend(["spotify"])
    controller = make_controller(backend)

    controller.handle_phrase("pause")

    assert controller._state.snapshot().current_state == "Paused"


def test_non_command_phrase_is_ignored() -> None:
    backend = FakeBackend(["spotify"])
    controller = make_controller(backend)

    assert controller.handle_phrase("hello there") is False
    assert backend.executed == []


def test_duplicate_command_is_suppressed() -> None:
    backend = FakeBackend(["spotify"])
    clock = Clock(100.0)
    controller = make_controller(backend, clock)

    assert controller.handle_phrase("play") is True
    clock.now = 100.2
    assert controller.handle_phrase("play") is False
    assert backend.executed == [("spotify", Intent.PLAY)]


def test_duplicate_allowed_after_guard() -> None:
    backend = FakeBackend(["spotify"])
    clock = Clock(100.0)
    controller = make_controller(backend, clock)

    controller.handle_phrase("play")
    clock.now = 101.0
    assert controller.handle_phrase("play") is True
    assert len(backend.executed) == 2


def test_records_target_after_success() -> None:
    backend = FakeBackend(["spotify"])
    controller = make_controller(backend)

    controller.handle_phrase("play")

    assert controller._resolver.last_target == "spotify"


def test_missing_playerctl_logs_hint_once(caplog) -> None:
    backend = FakeBackend(["spotify"], available=False)
    controller = make_controller(backend)

    with caplog.at_level(logging.INFO):
        assert controller.handle_intent(Intent.PLAY) is False
        assert controller.handle_intent(Intent.PAUSE) is False

    hints = [record for record in caplog.records if "Install playerctl" in record.message]
    assert len(hints) == 1


def test_no_player_found_returns_false(caplog) -> None:
    controller = make_controller(FakeBackend([]))

    with caplog.at_level(logging.WARNING):
        assert controller.handle_intent(Intent.PLAY) is False

    assert any("No unambiguous media player" in record.message for record in caplog.records)


def test_backend_failure_returns_false_and_does_not_record() -> None:
    backend = FakeBackend(["spotify"], result=CommandResult(1, stderr="boom"))
    controller = make_controller(backend)

    assert controller.handle_phrase("play") is False
    assert controller._state.snapshot().last_intent is None


class FakeVolume:
    def __init__(self, result=None) -> None:
        self.result = result or CommandResult(0)
        self.calls: list[Intent] = []

    def change(self, intent: Intent) -> CommandResult:
        self.calls.append(intent)
        return self.result


def test_volume_intent_uses_volume_backend() -> None:
    backend = FakeBackend(["spotify"])
    volume = FakeVolume()
    controller = MediaController(
        backend,
        PlayerResolver(backend),
        IntentMatcher(),
        StateStore(),
        volume_backend=volume,
    )

    assert controller.handle_phrase("volume up") is True
    assert volume.calls == [Intent.VOLUME_UP]
    assert backend.executed == []


def test_volume_failure_is_reported() -> None:
    backend = FakeBackend(["spotify"])
    volume = FakeVolume(CommandResult(1, stderr="no sink"))
    controller = MediaController(
        backend,
        PlayerResolver(backend),
        IntentMatcher(),
        StateStore(),
        volume_backend=volume,
    )

    assert controller.handle_phrase("volume down") is False


def test_next_warns_when_player_cannot_skip(caplog) -> None:
    backend = FakeBackend(["brave"], capabilities=PlayerCapabilities(can_go_next=False))
    controller = make_controller(backend)

    with caplog.at_level(logging.WARNING):
        assert controller.handle_phrase("next") is False

    assert backend.executed == []
    assert any("cannot skip forward" in record.message for record in caplog.records)


def test_previous_warns_when_player_cannot_skip(caplog) -> None:
    backend = FakeBackend(["brave"], capabilities=PlayerCapabilities(can_go_previous=False))
    controller = make_controller(backend)

    with caplog.at_level(logging.WARNING):
        assert controller.handle_phrase("previous") is False

    assert any("cannot skip back" in record.message for record in caplog.records)


def test_next_executes_when_supported() -> None:
    backend = FakeBackend(["spotify"], capabilities=PlayerCapabilities(can_go_next=True))
    controller = make_controller(backend)

    assert controller.handle_phrase("next") is True
    assert backend.executed == [("spotify", Intent.NEXT)]
