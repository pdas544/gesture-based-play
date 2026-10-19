"""Volume control backends.

Browser MPRIS implementations (Chromium/Brave/Firefox) expose a read-only
``Volume`` property, so ``playerctl volume`` silently does nothing there. The
system backends drive PipeWire/ALSA directly, which works regardless of the
player.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from typing import Protocol

from .intents import Intent
from .players import CommandResult, PlayerBackend, PlayerResolver

logger = logging.getLogger(__name__)

VOLUME_INTENTS = (Intent.VOLUME_UP, Intent.VOLUME_DOWN)


def _is_up(intent: Intent) -> bool:
    return intent == Intent.VOLUME_UP


class VolumeBackend(Protocol):
    """Changes the output volume for a volume intent."""

    def change(self, intent: Intent) -> CommandResult: ...


class PlayerctlVolumeBackend:
    """Change per-player volume through the MPRIS backend."""

    def __init__(self, backend: PlayerBackend, resolver: PlayerResolver) -> None:
        self._backend = backend
        self._resolver = resolver

    def change(self, intent: Intent) -> CommandResult:
        target = self._resolver.resolve(intent)
        if not target:
            return CommandResult(1, stderr="no unambiguous media player")
        return self._backend.execute(target, intent)


class SystemVolumeBackend:
    """Change the default audio sink volume via wpctl/amixer/pactl."""

    def __init__(
        self,
        *,
        step_percent: int = 5,
        run: Callable[..., object] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._step = step_percent
        self._run = run
        self._which = which

    def _commands(self, intent: Intent) -> list[list[str]]:
        sign = "+" if _is_up(intent) else "-"
        step = f"{self._step}%"
        commands: list[list[str]] = []

        wpctl = self._which("wpctl")
        if wpctl:
            commands.append([wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{step}{sign}"])

        amixer = self._which("amixer")
        if amixer:
            commands.append([amixer, "-D", "pulse", "sset", "Master", f"{step}{sign}"])

        pactl = self._which("pactl")
        if pactl:
            commands.append([pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{step}"])

        return commands

    def change(self, intent: Intent) -> CommandResult:
        commands = self._commands(intent)
        if not commands:
            return CommandResult(1, stderr="no system volume tool found (wpctl/amixer/pactl)")

        last = CommandResult(1, stderr="no system volume tool succeeded")
        for command in commands:
            try:
                completed = self._run(command, capture_output=True, text=True)
            except OSError as error:
                last = CommandResult(1, stderr=str(error))
                continue

            last = CommandResult(
                getattr(completed, "returncode", 1),
                getattr(completed, "stdout", ""),
                getattr(completed, "stderr", ""),
            )
            if last.ok:
                return last

        return last


class AutoVolumeBackend:
    """Try per-player volume, then fall back to system volume."""

    def __init__(self, mpris: VolumeBackend, system: VolumeBackend) -> None:
        self._mpris = mpris
        self._system = system

    def change(self, intent: Intent) -> CommandResult:
        result = self._mpris.change(intent)
        if result.ok:
            return result

        logger.debug(
            "MPRIS volume failed (%s); falling back to system volume",
            result.stderr.strip() or f"rc={result.returncode}",
        )
        return self._system.change(intent)


def build_volume_backend(
    mode: str,
    *,
    backend: PlayerBackend,
    resolver: PlayerResolver,
    step_percent: int = 5,
) -> VolumeBackend:
    """Construct the configured volume backend (``auto``/``system``/``mpris``)."""
    mode = mode.strip().lower()
    if mode == "system":
        return SystemVolumeBackend(step_percent=step_percent)
    if mode == "mpris":
        return PlayerctlVolumeBackend(backend, resolver)
    if mode == "auto":
        return AutoVolumeBackend(
            PlayerctlVolumeBackend(backend, resolver),
            SystemVolumeBackend(step_percent=step_percent),
        )
    raise ValueError(f"unknown volume backend {mode!r}; expected auto, system, or mpris")
