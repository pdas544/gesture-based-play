"""Voice intents and phrase matching.

Matching is a pure function of (configured phrases, recognized text), which
makes it straightforward to unit test without any audio or OS integration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class Intent(str, Enum):
    """Supported media-control intents."""

    PLAY = "PLAY"
    PAUSE = "PAUSE"
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"
    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"


DEFAULT_PHRASES: Mapping[Intent, tuple[str, ...]] = MappingProxyType(
    {
        Intent.PLAY: ("play", "resume", "start", "continue", "begin"),
        Intent.PAUSE: ("pause", "stop", "halt", "hold", "wait"),
        Intent.NEXT: ("next", "skip", "forward", "advance"),
        Intent.PREVIOUS: ("previous", "back", "backward", "rewind", "go back"),
        Intent.VOLUME_UP: ("volume up", "louder", "increase volume", "turn up", "turn it up"),
        Intent.VOLUME_DOWN: (
            "volume down",
            "quieter",
            "decrease volume",
            "turn down",
            "turn it down",
            "softer",
        ),
    }
)


@dataclass(frozen=True)
class _MatcherEntry:
    intent: Intent
    phrase: str
    pattern: re.Pattern[str]


class IntentMatcher:
    """Map recognized text to an :class:`Intent` using word-boundary regexes.

    Patterns are compiled once and ordered by descending phrase length so that
    composite phrases such as ``"volume up"`` win over shorter alternatives.
    Word boundaries prevent false positives like ``"pause"`` inside ``"because"``.
    """

    def __init__(self, phrases: Mapping[Intent, tuple[str, ...]] | None = None) -> None:
        mapping = phrases if phrases is not None else DEFAULT_PHRASES
        entries: list[tuple[int, int, _MatcherEntry]] = []
        for order, (intent, phrase_list) in enumerate(mapping.items()):
            for phrase in phrase_list:
                normalized = phrase.strip().lower()
                if not normalized:
                    continue
                pattern = re.compile(r"\b" + re.escape(normalized) + r"\b")
                entries.append((len(normalized), order, _MatcherEntry(intent, normalized, pattern)))

        entries.sort(key=lambda item: (-item[0], item[1]))
        self._entries: tuple[_MatcherEntry, ...] = tuple(entry for _, _, entry in entries)

    @property
    def intents(self) -> tuple[Intent, ...]:
        """Intents that have at least one configured phrase."""
        seen: list[Intent] = []
        for entry in self._entries:
            if entry.intent not in seen:
                seen.append(entry.intent)
        return tuple(seen)

    def phrases(self) -> list[str]:
        """All configured phrases (used to build the recognition grammar)."""
        return [entry.phrase for entry in self._entries]

    def match(self, text: str | None) -> Intent | None:
        """Return the matching intent, or ``None`` if the text is not a command."""
        if not text:
            return None
        normalized = " ".join(text.split()).lower()
        if not normalized:
            return None
        for entry in self._entries:
            if entry.pattern.search(normalized):
                return entry.intent
        return None
