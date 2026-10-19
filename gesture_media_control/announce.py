"""Spoken announcements (the assistant's greeting)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Announcer(Protocol):
    """Speaks short phrases and reports whether speech is in progress."""

    @property
    def is_speaking(self) -> bool: ...

    def say(self, text: str) -> None: ...

    def stop(self) -> None: ...


class NullAnnouncer:
    """No-op announcer used when TTS is disabled."""

    @property
    def is_speaking(self) -> bool:
        return False

    def say(self, _text: str) -> None:
        return

    def stop(self) -> None:
        return


class SpeechDispatcherAnnouncer:
    """Speak through Speech Dispatcher's ``spd-say``."""

    def __init__(
        self,
        *,
        command: str = "spd-say",
        extra_args: Sequence[str] = ("-w",),
        which: Callable[[str], str | None] = shutil.which,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._path = which(command)
        self._extra = tuple(extra_args)
        self._popen = popen
        self._process: Any | None = None
        self._lock = threading.Lock()
        self._missing_logged = False

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            if self._process is None:
                return False
            if self._process.poll() is None:
                return True
            self._process = None
            return False

    def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self._path:
            if not self._missing_logged:
                logger.warning("spd-say not found; spoken announcements are disabled.")
                self._missing_logged = True
            return

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            try:
                self._process = self._popen(
                    [self._path, *self._extra, text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                logger.exception("Failed to start text-to-speech")
                self._process = None

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                logger.debug("Failed to terminate text-to-speech", exc_info=True)
