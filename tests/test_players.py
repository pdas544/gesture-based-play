from __future__ import annotations

from types import SimpleNamespace

from gesture_media_control.intents import Intent
from gesture_media_control.players import (
    CommandResult,
    PlayerCapabilities,
    PlayerctlBackend,
    PlayerResolver,
    parse_player_capabilities,
)


class FakeRun:
    """Stand-in for ``subprocess.run`` that records invocations."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


class FakeBackend:
    def __init__(self, players=(), statuses=None) -> None:
        self._players = list(players)
        self._statuses = dict(statuses or {})
        self.executed: list[tuple[str, Intent]] = []
        self.available = True
        self.result = CommandResult(0)

    def is_available(self) -> bool:
        return self.available

    def list_players(self) -> list[str]:
        return list(self._players)

    def get_status(self, player: str) -> str | None:
        return self._statuses.get(player)

    def execute(self, player: str, intent: Intent) -> CommandResult:
        self.executed.append((player, intent))
        return self.result


class FakeFocus:
    def __init__(self, hint: str | None) -> None:
        self._hint = hint

    def focused_player_hint(self) -> str | None:
        return self._hint


def test_backend_unavailable_without_path() -> None:
    backend = PlayerctlBackend(playerctl_path=None, run=FakeRun())
    backend._path = None
    assert backend.is_available() is False
    assert backend.list_players() == []


def test_backend_lists_players() -> None:
    run = FakeRun(stdout="spotify\nvlc\n\n")
    backend = PlayerctlBackend("/usr/bin/playerctl", run=run)

    assert backend.is_available() is True
    assert backend.list_players() == ["spotify", "vlc"]
    assert run.calls == [["/usr/bin/playerctl", "-l"]]


def test_backend_get_status_failure_returns_none() -> None:
    backend = PlayerctlBackend("/usr/bin/playerctl", run=FakeRun(returncode=1))
    assert backend.get_status("spotify") is None


def test_backend_execute_maps_intent_to_arguments() -> None:
    run = FakeRun()
    backend = PlayerctlBackend("/usr/bin/playerctl", run=run)

    backend.execute("spotify", Intent.VOLUME_UP)

    assert run.calls == [["/usr/bin/playerctl", "--player=spotify", "volume", "0.1+"]]


def test_backend_execute_handles_oserror() -> None:
    def boom(*_args, **_kwargs):
        raise OSError("not executable")

    backend = PlayerctlBackend("/usr/bin/playerctl", run=boom)
    result = backend.execute("spotify", Intent.PLAY)

    assert result.ok is False
    assert "not executable" in result.stderr


def test_parse_player_capabilities() -> None:
    raw = (
        "({'CanControl': <true>, 'CanGoNext': <false>, 'CanGoPrevious': <false>, "
        "'CanPlay': <true>, 'CanPause': <true>})"
    )

    assert parse_player_capabilities(raw) == PlayerCapabilities(
        can_control=True,
        can_play=True,
        can_pause=True,
        can_go_next=False,
        can_go_previous=False,
    )


def test_parse_player_capabilities_rejects_garbage() -> None:
    assert parse_player_capabilities("error: no such name") is None


def test_backend_reads_capabilities_via_gdbus() -> None:
    run = FakeRun(stdout="({'CanGoNext': <false>, 'CanGoPrevious': <true>})")
    backend = PlayerctlBackend("/usr/bin/playerctl", gdbus_path="/usr/bin/gdbus", run=run)

    capabilities = backend.get_capabilities("brave.instance2")

    assert capabilities is not None
    assert capabilities.can_go_next is False
    assert capabilities.can_go_previous is True
    assert run.calls[0][0] == "/usr/bin/gdbus"
    assert "org.mpris.MediaPlayer2.brave.instance2" in run.calls[0]


def test_backend_capabilities_unavailable_without_gdbus() -> None:
    backend = PlayerctlBackend("/usr/bin/playerctl", gdbus_path=None, run=FakeRun())
    backend._gdbus = None

    assert backend.get_capabilities("spotify") is None


def test_resolver_returns_none_without_players() -> None:
    resolver = PlayerResolver(FakeBackend())
    assert resolver.resolve(Intent.PLAY) is None


def test_resolver_runtime_override_wins() -> None:
    resolver = PlayerResolver(FakeBackend(["spotify", "vlc"]))
    resolver.runtime_override = "vlc"
    assert resolver.resolve(Intent.PAUSE) == "vlc"


def test_resolver_preferred_player_wins() -> None:
    resolver = PlayerResolver(FakeBackend(["spotify", "vlc"]), preferred_player="vlc")
    assert resolver.resolve(Intent.PAUSE) == "vlc"


def test_resolver_uses_focused_player_when_unambiguous() -> None:
    backend = FakeBackend(["spotify", "vlc"])
    resolver = PlayerResolver(
        backend, focus_detector=FakeFocus("spotify"), prefer_focused_player=True
    )
    assert resolver.resolve(Intent.PAUSE) == "spotify"


def test_resolver_ambiguous_focus_falls_through() -> None:
    backend = FakeBackend(["spotify", "spot", "vlc"], statuses={"spotify": "Paused"})
    resolver = PlayerResolver(backend, focus_detector=FakeFocus("spot"), prefer_focused_player=True)
    # "spot" matches both spotify and spot -> ambiguous, so status heuristics decide.
    assert resolver.resolve(Intent.PLAY) == "spotify"


def test_resolver_unique_playing_player_for_pause() -> None:
    backend = FakeBackend(["spotify", "vlc"], statuses={"spotify": "Playing", "vlc": "Paused"})
    resolver = PlayerResolver(backend)
    assert resolver.resolve(Intent.PAUSE) == "spotify"


def test_resolver_unique_paused_player_for_play() -> None:
    backend = FakeBackend(["spotify", "vlc"], statuses={"spotify": "Playing", "vlc": "Paused"})
    resolver = PlayerResolver(backend)
    assert resolver.resolve(Intent.PLAY) == "vlc"


def test_resolver_remembers_last_target_for_stateful_intent() -> None:
    backend = FakeBackend(["spotify", "vlc"])
    resolver = PlayerResolver(backend)
    resolver.record_target("vlc")

    assert resolver.resolve(Intent.NEXT) == "vlc"


def test_resolver_single_player_fallback() -> None:
    resolver = PlayerResolver(FakeBackend(["spotify"]))
    assert resolver.resolve(Intent.VOLUME_UP) == "spotify"


def test_resolver_ambiguous_returns_none() -> None:
    resolver = PlayerResolver(FakeBackend(["spotify", "vlc"]))
    assert resolver.resolve(Intent.VOLUME_UP) is None
