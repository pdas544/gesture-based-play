from __future__ import annotations

from types import SimpleNamespace

from gesture_media_control.focus import SystemFocusDetector, parse_gnome_eval_output


def test_parse_gnome_eval_output_extracts_class() -> None:
    assert parse_gnome_eval_output("(true, 'Spotify')") == "spotify"


def test_parse_gnome_eval_output_handles_empty_string() -> None:
    assert parse_gnome_eval_output("(true, '')") is None


def test_parse_gnome_eval_output_rejects_unexpected_shapes() -> None:
    assert parse_gnome_eval_output("error: something went wrong") is None
    assert parse_gnome_eval_output("(true)") is None
    assert parse_gnome_eval_output("") is None


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_uses_xdotool_when_gdbus_missing() -> None:
    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return "/usr/bin/xdotool" if name == "xdotool" else None

    def fake_run(args, **_kwargs):
        calls.append(args)
        return _completed(0, "vlc\n")

    detector = SystemFocusDetector(run=fake_run, which=fake_which)

    assert detector.focused_player_hint() == "vlc"
    assert calls == [["/usr/bin/xdotool", "getactivewindow", "getwindowclassname"]]


def test_gnome_hint_preferred_over_xdotool() -> None:
    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}"

    def fake_run(args, **_kwargs):
        return _completed(0, "(true, 'Spotify')")

    detector = SystemFocusDetector(run=fake_run, which=fake_which)

    assert detector.focused_player_hint() == "spotify"


def test_missing_binaries_return_none() -> None:
    detector = SystemFocusDetector(run=lambda *a, **k: _completed(0), which=lambda _name: None)
    assert detector.focused_player_hint() is None


def test_oserror_is_swallowed() -> None:
    def boom(*_args, **_kwargs):
        raise OSError("exec format error")

    detector = SystemFocusDetector(run=boom, which=lambda name: f"/usr/bin/{name}")
    assert detector.focused_player_hint() is None
