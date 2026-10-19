"""MPRIS player control and target resolution.

``PlayerBackend`` is the seam between the application and the OS: the
production :class:`PlayerctlBackend` shells out to ``playerctl``, while tests
can supply a lightweight fake. :class:`PlayerResolver` contains the pure
target-selection heuristics and depends only on the backend + focus detector.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

from .focus import FocusDetector
from .intents import Intent

PLAYERCTL_ACTIONS: dict[Intent, tuple[str, ...]] = {
    Intent.PLAY: ("play",),
    Intent.PAUSE: ("pause",),
    Intent.NEXT: ("next",),
    Intent.PREVIOUS: ("previous",),
    Intent.VOLUME_UP: ("volume", "0.1+"),
    Intent.VOLUME_DOWN: ("volume", "0.1-"),
}

# Intents whose player resolution can use last-used / playback-status heuristics.
_STATEFUL_INTENTS = (Intent.PLAY, Intent.PAUSE, Intent.NEXT, Intent.PREVIOUS)


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a single backend command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class PlayerCapabilities:
    """Subset of MPRIS capability flags relevant to command support."""

    can_control: bool | None = None
    can_play: bool | None = None
    can_pause: bool | None = None
    can_go_next: bool | None = None
    can_go_previous: bool | None = None


def _parse_bool(text: str, property_name: str) -> bool | None:
    match = re.search(rf"'{re.escape(property_name)}': <(true|false)>", text)
    if match is None:
        return None
    return match.group(1) == "true"


def parse_player_capabilities(raw_output: str) -> PlayerCapabilities | None:
    """Parse the GVariant reply from ``Properties.GetAll`` for the Player interface."""
    if "CanControl" not in raw_output and "CanGoNext" not in raw_output:
        return None
    return PlayerCapabilities(
        can_control=_parse_bool(raw_output, "CanControl"),
        can_play=_parse_bool(raw_output, "CanPlay"),
        can_pause=_parse_bool(raw_output, "CanPause"),
        can_go_next=_parse_bool(raw_output, "CanGoNext"),
        can_go_previous=_parse_bool(raw_output, "CanGoPrevious"),
    )


class PlayerBackend(Protocol):
    """Abstract media-player backend."""

    def is_available(self) -> bool: ...

    def list_players(self) -> list[str]: ...

    def get_status(self, player: str) -> str | None: ...

    def get_capabilities(self, player: str) -> PlayerCapabilities | None: ...

    def execute(self, player: str, intent: Intent) -> CommandResult: ...


class PlayerctlBackend:
    """Concrete backend that drives MPRIS players through ``playerctl``."""

    def __init__(
        self,
        playerctl_path: str | None = None,
        *,
        gdbus_path: str | None = None,
        run=subprocess.run,
        which=shutil.which,
    ) -> None:
        self._path = playerctl_path if playerctl_path is not None else which("playerctl")
        self._gdbus = gdbus_path if gdbus_path is not None else which("gdbus")
        self._run = run

    @property
    def path(self) -> str | None:
        return self._path

    def is_available(self) -> bool:
        return bool(self._path)

    def _invoke(self, arguments: list[str]) -> CommandResult:
        if not self._path:
            return CommandResult(1, stderr="playerctl not found")
        try:
            completed = self._run([self._path, *arguments], capture_output=True, text=True)
        except OSError as error:  # missing binary, permission denied, ...
            return CommandResult(1, stderr=str(error))
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    def list_players(self) -> list[str]:
        result = self._invoke(["-l"])
        if not result.ok:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def get_status(self, player: str) -> str | None:
        result = self._invoke([f"--player={player}", "status"])
        if not result.ok:
            return None
        return result.stdout.strip()

    def get_capabilities(self, player: str) -> PlayerCapabilities | None:
        """Read MPRIS Player capability flags via ``gdbus`` (best effort)."""
        if not self._gdbus:
            return None
        try:
            completed = self._run(
                [
                    self._gdbus,
                    "call",
                    "--session",
                    "--dest",
                    f"org.mpris.MediaPlayer2.{player}",
                    "--object-path",
                    "/org/mpris/MediaPlayer2",
                    "--method",
                    "org.freedesktop.DBus.Properties.GetAll",
                    "org.mpris.MediaPlayer2.Player",
                ],
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if getattr(completed, "returncode", 1) != 0:
            return None
        return parse_player_capabilities(getattr(completed, "stdout", ""))

    def execute(self, player: str, intent: Intent) -> CommandResult:
        action = PLAYERCTL_ACTIONS.get(intent)
        if action is None:
            return CommandResult(1, stderr=f"unsupported intent: {intent}")
        return self._invoke([f"--player={player}", *action])


class PlayerResolver:
    """Choose the best player for an intent using ordered heuristics."""

    def __init__(
        self,
        backend: PlayerBackend,
        *,
        focus_detector: FocusDetector | None = None,
        preferred_player: str | None = None,
        prefer_focused_player: bool = True,
    ) -> None:
        self._backend = backend
        self._focus_detector = focus_detector
        self._preferred_player = preferred_player
        self._prefer_focused_player = prefer_focused_player
        self._runtime_override: str | None = None
        self._last_target: str | None = None

    @property
    def runtime_override(self) -> str | None:
        return self._runtime_override

    @runtime_override.setter
    def runtime_override(self, player: str | None) -> None:
        self._runtime_override = player

    @property
    def last_target(self) -> str | None:
        return self._last_target

    def record_target(self, player: str) -> None:
        """Remember the player that was successfully controlled."""
        self._last_target = player

    def resolve(self, intent: Intent) -> str | None:
        """Return the player to control, or ``None`` when ambiguous/absent."""
        players = self._backend.list_players()
        if not players:
            return None

        if self._runtime_override in players:
            return self._runtime_override

        if self._preferred_player in players:
            return self._preferred_player

        if self._prefer_focused_player and self._focus_detector is not None:
            focused = self._match_focused_player(players)
            if focused is not None:
                return focused

        if intent in _STATEFUL_INTENTS and self._last_target in players:
            return self._last_target

        statuses = {}
        for player in players:
            status = self._backend.get_status(player)
            if status:
                statuses[player] = status

        if intent in (Intent.PAUSE, Intent.NEXT, Intent.PREVIOUS):
            target = self._resolve_by_status(players, statuses, "Playing")
            if target is not None:
                return target
        elif intent == Intent.PLAY:
            target = self._resolve_by_status(players, statuses, "Paused")
            if target is not None:
                return target

        if len(players) == 1:
            return players[0]

        if self._last_target in players:
            return self._last_target

        return None

    def _match_focused_player(self, players: list[str]) -> str | None:
        hint = self._focus_detector.focused_player_hint()
        if not hint:
            return None
        matches = [player for player in players if hint in player.lower() or player.lower() in hint]
        if len(matches) == 1:
            return matches[0]
        return None

    def _resolve_by_status(
        self, players: list[str], statuses: dict[str, str], desired: str
    ) -> str | None:
        matches = [player for player in players if statuses.get(player) == desired]
        if len(matches) == 1:
            return matches[0]
        if self._last_target in matches:
            return self._last_target
        return None
