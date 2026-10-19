from __future__ import annotations

import pytest
from gesture_media_control.intents import DEFAULT_PHRASES, Intent, IntentMatcher


@pytest.fixture
def matcher() -> IntentMatcher:
    return IntentMatcher()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("play", Intent.PLAY),
        ("resume", Intent.PLAY),
        ("pause", Intent.PAUSE),
        ("stop", Intent.PAUSE),
        ("next", Intent.NEXT),
        ("skip", Intent.NEXT),
        ("previous", Intent.PREVIOUS),
        ("go back", Intent.PREVIOUS),
        ("volume up", Intent.VOLUME_UP),
        ("louder", Intent.VOLUME_UP),
        ("volume down", Intent.VOLUME_DOWN),
        ("softer", Intent.VOLUME_DOWN),
    ],
)
def test_matches_default_phrases(matcher: IntentMatcher, text: str, expected: Intent) -> None:
    assert matcher.match(text) is expected


def test_matching_is_case_and_whitespace_insensitive(matcher: IntentMatcher) -> None:
    assert matcher.match("  PLAY   the   song ") is Intent.PLAY
    assert matcher.match("Volume   UP") is Intent.VOLUME_UP


@pytest.mark.parametrize("text", [None, "", "   ", "nonsense words"])
def test_non_commands_return_none(matcher: IntentMatcher, text: str | None) -> None:
    assert matcher.match(text) is None


@pytest.mark.parametrize("text", ["because", "wonderful", "nextdoor neighbour"])
def test_word_boundaries_prevent_false_positives(matcher: IntentMatcher, text: str) -> None:
    # "because" contains "pause", but not as a whole word.
    assert matcher.match(text) is None


def test_composite_phrases_take_priority(matcher: IntentMatcher) -> None:
    # "turn it up" / "volume up" must not be confused with shorter fragments.
    assert matcher.match("please turn it up") is Intent.VOLUME_UP
    assert matcher.match("turn it down now") is Intent.VOLUME_DOWN


def test_phrases_returns_all_configured_phrases(matcher: IntentMatcher) -> None:
    expected = {phrase for phrases in DEFAULT_PHRASES.values() for phrase in phrases}
    assert set(matcher.phrases()) == expected


def test_intents_property_lists_unique_intents(matcher: IntentMatcher) -> None:
    assert set(matcher.intents) == set(DEFAULT_PHRASES)


def test_custom_phrase_mapping() -> None:
    custom = {Intent.PLAY: ("go",), Intent.PAUSE: ("freeze",)}
    matcher = IntentMatcher(custom)
    assert matcher.match("go") is Intent.PLAY
    assert matcher.match("freeze") is Intent.PAUSE
    assert matcher.match("play") is None
