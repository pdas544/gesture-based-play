from __future__ import annotations

from types import SimpleNamespace

from gesture_media_control import cli
from gesture_media_control.players import CommandResult


class FakeBackend:
    def __init__(self, players=(), statuses=None) -> None:
        self._players = list(players)
        self._statuses = dict(statuses or {})

    def is_available(self) -> bool:
        return True

    def list_players(self) -> list[str]:
        return list(self._players)

    def get_status(self, player: str) -> str | None:
        return self._statuses.get(player)

    def execute(self, player: str, intent) -> CommandResult:  # pragma: no cover - unused
        return CommandResult(0)


class StubApp:
    def __init__(self, players=(), statuses=None, preferred=None, override=None) -> None:
        self.backend = FakeBackend(players, statuses)
        self.resolver = SimpleNamespace(runtime_override=override, last_target=None)
        self.config = SimpleNamespace(preferred_player=preferred, prefer_focused_player=True)

    def status_line(self) -> str:
        return "State: Idle | Last command: — | Target: auto"


def run_command(app: StubApp, line: str) -> tuple[bool, list[str]]:
    output: list[str] = []
    keep_going = cli._handle_command(app, line, output.append)
    return keep_going, output


def test_quit_command_stops_loop() -> None:
    keep_going, _ = run_command(StubApp(), "q")
    assert keep_going is False


def test_help_command_prints_help() -> None:
    _, output = run_command(StubApp(), "help")
    assert output == [cli.HELP_TEXT]


def test_status_command_prints_status() -> None:
    _, output = run_command(StubApp(), "status")
    assert output and "State: Idle" in output[0]


def test_players_command_lists_statuses() -> None:
    app = StubApp(["spotify", "vlc"], statuses={"spotify": "Playing"})

    _, output = run_command(app, "players")

    assert "  - spotify (Playing)" in output
    assert "  - vlc (unknown)" in output


def test_players_command_with_none_detected() -> None:
    _, output = run_command(StubApp(), "players")
    assert output == ["No MPRIS players detected."]


def test_cycle_target_without_players() -> None:
    _, output = run_command(StubApp(), "t")
    assert "No playerctl players found to cycle" in output[0]


def test_cycle_target_wraps_around() -> None:
    app = StubApp(["spotify", "vlc"])

    run_command(app, "t")
    assert app.resolver.runtime_override == "spotify"

    run_command(app, "t")
    assert app.resolver.runtime_override == "vlc"

    run_command(app, "t")
    assert app.resolver.runtime_override == "spotify"


def test_unknown_command_reports_error() -> None:
    _, output = run_command(StubApp(), "frobnicate")
    assert "Unknown command" in output[0]


def test_blank_line_does_nothing() -> None:
    keep_going, output = run_command(StubApp(), "")
    assert keep_going is True
    assert output == []


def test_banner_mentions_commands_and_players() -> None:
    output: list[str] = []
    cli.print_banner(StubApp(["spotify"]), output.append)
    text = "\n".join(output)

    assert "Voice Media Controller" in text
    assert "spotify" in text


def test_parser_accepts_documented_flags() -> None:
    args = cli.build_parser().parse_args(
        ["--player", "vlc", "--no-focused", "--log-level", "DEBUG"]
    )

    assert args.player == "vlc"
    assert args.no_focused is True
    assert args.log_level == "DEBUG"
