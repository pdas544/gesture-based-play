"""Command-line interface: argument parsing, banner, and console loop."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .app import Application, build_application
from .config import Config

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
DATE_FORMAT = "%H:%M:%S"

HELP_TEXT = "Commands: t (cycle target), players (list), status, help, q (quit)"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-media-control",
        description="Control Linux media playback with voice commands.",
    )
    parser.add_argument("--model-path", type=Path, default=None, help="Path to the Vosk model")
    parser.add_argument("--player", default=None, help="Preferred MPRIS player name")
    parser.add_argument(
        "--no-focused",
        action="store_true",
        help="Disable focused-window player detection",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print player capabilities and exit",
    )
    parser.add_argument(
        "--no-wake",
        action="store_true",
        help="Disable the wake word and accept commands continuously",
    )
    parser.add_argument(
        "--wake-engine",
        choices=["auto", "openwakeword", "vosk"],
        default=None,
        help="Wake-word engine (default: auto)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser


def _stamp() -> str:
    return datetime.now().strftime(DATE_FORMAT)


def print_banner(app: Application, output: Callable[[str], None]) -> None:
    output("=" * 60)
    output("Voice Media Controller - Ready")
    output("=" * 60)
    output("Voice commands (English):")
    output("  - 'play' / 'resume'        -> Start playback")
    output("  - 'pause' / 'stop'         -> Pause playback")
    output("  - 'next' / 'skip'          -> Next track")
    output("  - 'previous' / 'back'      -> Previous track")
    output("  - 'volume up' / 'louder'   -> Increase volume")
    output("  - 'volume down' / 'softer' -> Decrease volume")
    output("")
    output("Keyboard controls: 't' cycle target, 'q' quit, Ctrl+C quit")
    output("=" * 60)

    if app.config.wake_enabled:
        output(f"Wake word: {app.assistant.wake_description}")
        timeout = app.config.session_timeout_seconds
        output(f"  Say the wake word; commands time out after {timeout:.0f}s.")
    else:
        output("Wake word: disabled (commands accepted continuously)")

    if not app.backend.is_available():
        output("playerctl not found. Install it for media control: sudo apt install playerctl")
    if app.config.preferred_player:
        output(f"Preferred player: {app.config.preferred_player}")
    if app.config.prefer_focused_player:
        output("Focused player detection: enabled (GNOME/Wayland + X11 fallback)")

    players = app.backend.list_players()
    if players:
        output(f"Available players: {', '.join(players)}")
    else:
        output("No MPRIS players detected yet. Open a media player and try again.")
    output("=" * 60)


def _status(app: Application) -> str:
    return f"[{_stamp()}] {app.status_line()}"


def _cycle_target(app: Application, output: Callable[[str], None]) -> None:
    players = app.backend.list_players()
    if not players:
        output(f"[{_stamp()}] No playerctl players found to cycle")
        return

    current = app.resolver.runtime_override
    if current not in players:
        app.resolver.runtime_override = players[0]
    else:
        app.resolver.runtime_override = players[(players.index(current) + 1) % len(players)]

    output(f"[{_stamp()}] Runtime target set to: {app.resolver.runtime_override}")
    output(_status(app))


def _list_players(app: Application, output: Callable[[str], None]) -> None:
    players = app.backend.list_players()
    if not players:
        output("No MPRIS players detected.")
        return
    for player in players:
        status = app.backend.get_status(player) or "unknown"
        output(f"  - {player} ({status})")


def run_diagnose(app: Application, output: Callable[[str], None]) -> None:
    """Print player capabilities and the active volume configuration."""
    output("=" * 60)
    output("Diagnostics")
    output("=" * 60)
    playerctl_path = getattr(app.backend, "path", None)
    output(f"playerctl: {playerctl_path or 'not found'}")
    output(f"volume backend: {app.config.volume_backend} (step {app.config.volume_step_percent}%)")
    output(f"wake word: {app.assistant.wake_description}")
    output(f"session timeout: {app.config.session_timeout_seconds:.1f}s")

    players = app.backend.list_players()
    if not players:
        output("players: none")
        return

    lookup = getattr(app.backend, "get_capabilities", None)
    for player in players:
        status = app.backend.get_status(player) or "unknown"
        output(f"- {player}: {status}")
        capabilities = lookup(player) if lookup else None
        if capabilities is None:
            output("    capabilities: unavailable")
            continue
        output(
            "    "
            f"can_control={capabilities.can_control} "
            f"can_go_next={capabilities.can_go_next} "
            f"can_go_previous={capabilities.can_go_previous}"
        )


def _handle_command(app: Application, line: str, output: Callable[[str], None]) -> bool:
    """Process one console command; return False to quit."""
    if line == "q":
        return False
    if line == "t":
        _cycle_target(app, output)
    elif line == "status":
        output(_status(app))
    elif line == "players":
        _list_players(app, output)
    elif line in ("help", "?"):
        output(HELP_TEXT)
    elif line:
        output(f"Unknown command: {line!r}. Type 'help' for available commands.")
    return True


def run(
    app: Application,
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> int:
    """Start recognition and run the interactive console until quit."""
    print_banner(app, output)

    if app.assistant.start():
        if app.config.wake_enabled:
            output(f"Listening for the wake word ({app.assistant.wake_description}).\n")
        else:
            output("Listening for voice commands. Speak clearly into your microphone.\n")
    else:
        output("Voice recognition could not start. Press 'q' to quit.\n")

    try:
        while True:
            try:
                line = input_fn("> ").strip().lower()
            except EOFError:
                break
            if not _handle_command(app, line, output):
                break
    except KeyboardInterrupt:
        output("\nInterrupted.")
    finally:
        app.assistant.stop()
        output("Exiting. Goodbye!")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    config = Config.from_env()
    overrides: dict[str, object] = {}
    if args.model_path is not None:
        overrides["model_path"] = Path(args.model_path).expanduser()
    if args.player is not None:
        overrides["preferred_player"] = args.player
    if args.no_focused:
        overrides["prefer_focused_player"] = False
    if args.no_wake:
        overrides["wake_enabled"] = False
    if args.wake_engine is not None:
        overrides["wake_engine"] = args.wake_engine
    if overrides:
        config = replace(config, **overrides)

    app = build_application(config)
    if args.diagnose:
        run_diagnose(app, print)
        return 0
    return run(app)
