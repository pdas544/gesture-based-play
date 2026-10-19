from __future__ import annotations

from types import SimpleNamespace

import pytest
from gesture_media_control.intents import Intent
from gesture_media_control.players import CommandResult, PlayerResolver
from gesture_media_control.volume import (
    AutoVolumeBackend,
    PlayerctlVolumeBackend,
    SystemVolumeBackend,
    build_volume_backend,
)


class FakeRun:
    def __init__(self, returncodes=None) -> None:
        self.returncodes = list(returncodes or [0])
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        code = self.returncodes.pop(0) if self.returncodes else 0
        return SimpleNamespace(returncode=code, stdout="", stderr="" if code == 0 else "failed")


class FakeWhich:
    def __init__(self, available=()) -> None:
        self.available = set(available)

    def __call__(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.available else None


class FakeVolume:
    def __init__(self, result=None) -> None:
        self.result = result or CommandResult(0)
        self.calls: list[Intent] = []

    def change(self, intent: Intent) -> CommandResult:
        self.calls.append(intent)
        return self.result


class FakeBackend:
    def __init__(self) -> None:
        self._players = ["spotify"]
        self.executed: list[tuple[str, Intent]] = []
        self.result = CommandResult(0)

    def is_available(self) -> bool:
        return True

    def list_players(self) -> list[str]:
        return list(self._players)

    def get_status(self, _player: str) -> str | None:
        return "Playing"

    def execute(self, player: str, intent: Intent) -> CommandResult:
        self.executed.append((player, intent))
        return self.result


def test_system_volume_up_uses_wpctl() -> None:
    run = FakeRun()
    backend = SystemVolumeBackend(run=run, which=FakeWhich({"wpctl"}))

    result = backend.change(Intent.VOLUME_UP)

    assert result.ok is True
    assert run.calls == [["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"]]


def test_system_volume_down_uses_configured_step() -> None:
    run = FakeRun()
    backend = SystemVolumeBackend(step_percent=10, run=run, which=FakeWhich({"wpctl"}))

    backend.change(Intent.VOLUME_DOWN)

    assert run.calls == [["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"]]


def test_system_volume_falls_back_to_amixer() -> None:
    run = FakeRun([1, 0])
    backend = SystemVolumeBackend(run=run, which=FakeWhich({"wpctl", "amixer"}))

    result = backend.change(Intent.VOLUME_UP)

    assert result.ok is True
    assert [call[0] for call in run.calls] == ["/usr/bin/wpctl", "/usr/bin/amixer"]
    assert run.calls[1] == ["/usr/bin/amixer", "-D", "pulse", "sset", "Master", "5%+"]


def test_system_volume_pactl_argument_order() -> None:
    run = FakeRun()
    backend = SystemVolumeBackend(run=run, which=FakeWhich({"pactl"}))

    backend.change(Intent.VOLUME_DOWN)

    assert run.calls == [["/usr/bin/pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"]]


def test_system_volume_without_tools_reports_error() -> None:
    backend = SystemVolumeBackend(run=FakeRun(), which=FakeWhich())

    result = backend.change(Intent.VOLUME_UP)

    assert result.ok is False
    assert "no system volume tool" in result.stderr


def test_system_volume_handles_oserror_and_tries_next() -> None:
    def run(args, **_kwargs):
        if args[0].endswith("wpctl"):
            raise OSError("boom")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    backend = SystemVolumeBackend(run=run, which=FakeWhich({"wpctl", "amixer"}))

    assert backend.change(Intent.VOLUME_UP).ok is True


def test_auto_volume_prefers_mpris() -> None:
    mpris = FakeVolume(CommandResult(0))
    system = FakeVolume(CommandResult(0))

    AutoVolumeBackend(mpris, system).change(Intent.VOLUME_UP)

    assert mpris.calls == [Intent.VOLUME_UP]
    assert system.calls == []


def test_auto_volume_falls_back_to_system() -> None:
    mpris = FakeVolume(CommandResult(1, stderr="not supported"))
    system = FakeVolume(CommandResult(0))

    result = AutoVolumeBackend(mpris, system).change(Intent.VOLUME_DOWN)

    assert result.ok is True
    assert system.calls == [Intent.VOLUME_DOWN]


def test_playerctl_volume_resolves_target() -> None:
    backend = FakeBackend()
    resolver = PlayerResolver(backend)
    volume = PlayerctlVolumeBackend(backend, resolver)

    assert volume.change(Intent.VOLUME_UP).ok is True
    assert backend.executed == [("spotify", Intent.VOLUME_UP)]


def test_playerctl_volume_without_player_fails() -> None:
    backend = FakeBackend()
    backend._players = []  # type: ignore[attr-defined]
    volume = PlayerctlVolumeBackend(backend, PlayerResolver(backend))

    result = volume.change(Intent.VOLUME_UP)

    assert result.ok is False


def test_build_volume_backend_modes() -> None:
    backend = FakeBackend()
    resolver = PlayerResolver(backend)

    assert isinstance(
        build_volume_backend("system", backend=backend, resolver=resolver),
        SystemVolumeBackend,
    )
    assert isinstance(
        build_volume_backend("mpris", backend=backend, resolver=resolver),
        PlayerctlVolumeBackend,
    )
    assert isinstance(
        build_volume_backend("auto", backend=backend, resolver=resolver),
        AutoVolumeBackend,
    )
    with pytest.raises(ValueError):
        build_volume_backend("bogus", backend=backend, resolver=resolver)
