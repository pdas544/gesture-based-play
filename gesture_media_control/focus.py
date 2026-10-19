"""Focused-window detection.

Maps the currently focused application to a likely MPRIS player name so that a
command such as "pause" targets the player the user is actually looking at.

The GNOME path uses ``org.gnome.Shell.Eval`` (deprecated on newer GNOME, so the
call is best-effort), with an ``xdotool`` fallback for X11.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

GNOME_FOCUS_EXPRESSION = (
    "global.display.focus_window ? global.display.focus_window.wm_class.toLowerCase() : ''"
)


def parse_gnome_eval_output(raw_output: str) -> str | None:
    """Parse the ``org.gnome.Shell.Eval`` reply and return a wm_class hint.

    A successful reply looks like ``(true, 'spotify')``. Anything that does not
    match the expected shape yields ``None``.
    """
    text = raw_output.strip()
    if not text.startswith("("):
        return None

    first_quote = text.find("'")
    last_quote = text.rfind("'")
    if first_quote == -1 or last_quote <= first_quote:
        return None

    value = text[first_quote + 1 : last_quote].strip().lower()
    return value or None


class FocusDetector(Protocol):
    """Supplies a hint about which application is focused, if available."""

    def focused_player_hint(self) -> str | None: ...


class SystemFocusDetector:
    """Detect the focused application using GNOME Shell or ``xdotool``."""

    def __init__(self, *, run=subprocess.run, which=shutil.which) -> None:
        self._run = run
        self._gdbus = which("gdbus")
        self._xdotool = which("xdotool")

    def focused_player_hint(self) -> str | None:
        return self._gnome_hint() or self._x11_hint()

    def _gnome_hint(self) -> str | None:
        if not self._gdbus:
            return None
        try:
            result = self._run(
                [
                    self._gdbus,
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.Shell",
                    "--object-path",
                    "/org/gnome/Shell",
                    "--method",
                    "org.gnome.Shell.Eval",
                    GNOME_FOCUS_EXPRESSION,
                ],
                capture_output=True,
                text=True,
            )
        except OSError:
            return None

        if result.returncode == 0:
            return parse_gnome_eval_output(result.stdout)
        return None

    def _x11_hint(self) -> str | None:
        if not self._xdotool:
            return None
        try:
            result = self._run(
                [self._xdotool, "getactivewindow", "getwindowclassname"],
                capture_output=True,
                text=True,
            )
        except OSError:
            return None

        if result.returncode == 0:
            value = result.stdout.strip().lower()
            return value or None
        return None
