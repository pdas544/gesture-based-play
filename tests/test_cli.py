from __future__ import annotations

import threading
from types import SimpleNamespace

from gesture_media_control import cli
from gesture_media_control.players import CommandResult, PlayerCapabilities


class FakeBackend:
    def __init__(self, players=(), statuses=None, capabilities=None) -> None:
        self._players = list(players)
        self._statuses = dict(statuses or {})
        self._capabilities = capabilities
        self.path = "/usr/bin/playerctl"

    def is_available(self) -> bool:
        return True

    def list_players(self) -> list[str]:
        return list(self._players)

    def get_status(self, player: str) -> str | None:
        return self._statuses.get(player)

    def get_capabilities(self, _player: str) -> PlayerCapabilities | None:
        return self._capabilities

    def execute(self, player: str, intent) -> CommandResult:  # pragma: no cover - unused
        return CommandResult(0)


class StubAssistant:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.wake_description = "Vosk (hey lenovo, ok lenovo)"

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True


class StubApp:
    def __init__(
        self, players=(), statuses=None, preferred=None, override=None, capabilities=None
    ) -> None:
        self.backend = FakeBackend(players, statuses, capabilities)
        self.resolver = SimpleNamespace(runtime_override=override, last_target=None)
        self.config = SimpleNamespace(
            preferred_player=preferred,
            prefer_focused_player=True,
            volume_backend="auto",
            volume_step_percent=5,
            wake_enabled=True,
            session_timeout_seconds=10.0,
        )
        self.assistant = StubAssistant()

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
    assert "Wake word: Vosk" in text


def test_parser_accepts_documented_flags() -> None:
    args = cli.build_parser().parse_args(
        ["--player", "vlc", "--no-focused", "--log-level", "DEBUG"]
    )

    assert args.player == "vlc"
    assert args.no_focused is True
    assert args.log_level == "DEBUG"
    assert args.no_wake is False
    assert args.wake_engine is None
    assert args.daemon is False


def test_parser_accepts_wake_flags() -> None:
    args = cli.build_parser().parse_args(["--no-wake", "--wake-engine", "vosk"])

    assert args.no_wake is True
    assert args.wake_engine == "vosk"


def test_run_service_starts_and_stops_until_signalled() -> None:
    app = StubApp(["spotify"])
    stop = threading.Event()
    stop.set()
    output: list[str] = []

    code = cli.run_service(app, output=output.append, stop_event=stop, install_signals=False)

    assert code == 0
    assert app.assistant.started is True
    assert app.assistant.stopped is True
    assert any("Voice Media Controller" in line for line in output)


def test_diagnose_reports_capabilities() -> None:
    app = StubApp(
        ["brave.instance2"],
        statuses={"brave.instance2": "Paused"},
        capabilities=PlayerCapabilities(can_go_next=False, can_go_previous=False),
    )
    output: list[str] = []

    cli.run_diagnose(app, output.append)

    text = "\n".join(output)
    assert "playerctl: /usr/bin/playerctl" in text
    assert "volume backend: auto" in text
    assert "wake word: Vosk" in text
    assert "session timeout: 10.0s" in text
    assert "brave.instance2: Paused" in text
    assert "can_go_next=False" in text


def test_diagnose_with_no_players() -> None:
    output: list[str] = []
    cli.run_diagnose(StubApp(), output.append)
    assert "players: none" in "\n".join(output)
