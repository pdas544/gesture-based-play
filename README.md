# Gesture Media Control (voice)

Control Linux media playback with your voice. Speech is transcribed offline with
[Vosk](https://alphacephei.com/vosk/) and translated into
[`playerctl`](https://github.com/altdesktop/playerctl) MPRIS commands, so it works
with Spotify, VLC, MPV, browsers, and any other MPRIS-compliant player.

> The repository name mentions "gesture"; the current implementation is
> **voice-only**. Gesture input is not implemented yet.

## Features

- Offline speech recognition (no cloud calls)
- Grammar-constrained recognition tuned for short command words
- Smart player targeting: runtime override → preferred player → focused window →
  playing/paused heuristics
- Duplicate-command suppression
- Interactive console with player listing, status, and target cycling
- Graceful degradation when optional dependencies or players are missing

## Voice commands

| Intent        | Example phrases                                    |
| ------------- | -------------------------------------------------- |
| Play          | play, resume, start, continue, begin               |
| Pause         | pause, stop, halt, hold, wait                      |
| Next          | next, skip, forward, advance                       |
| Previous      | previous, back, backward, rewind, go back          |
| Volume up     | volume up, louder, increase volume, turn up        |
| Volume down   | volume down, quieter, decrease volume, turn down   |

## Requirements

- Python 3.10+
- `playerctl` (`sudo apt install playerctl`)
- A Vosk speech model unpacked into `models/`, e.g.
  `models/vosk-model-small-en-us-0.15/`
- Optional for focused-window detection: `gdbus` (GNOME) or `xdotool` (X11)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For development (tests + linting):

```bash
pip install -r requirements-dev.txt
```

## Run

```bash
python gesture-media-control.py
# or, after `pip install -e .`
voice-media-control
# or
python -m gesture_media_control
```

Console commands: `t` cycle target player, `players` list players, `status` show
state, `help` show help, `q` quit, `Ctrl+C` quit.

## Configuration

Configuration is read from environment variables (see
`gesture_media_control/config.py`):

| Variable                    | Default            | Description                          |
| --------------------------- | ------------------ | ------------------------------------ |
| `VMC_MODEL_PATH`            | `models/...`       | Path to the Vosk model directory     |
| `VMC_SAMPLE_RATE`           | `16000`            | Audio sample rate                    |
| `VMC_AUDIO_BLOCK_SIZE`      | `800`              | Frames per audio block               |
| `VMC_TRANSITION_GUARD`      | `0.5`              | Duplicate-command guard (seconds)    |
| `VMC_PREFERRED_PLAYER`      | *(unset)*          | Preferred MPRIS player name          |
| `VMC_PREFER_FOCUSED_PLAYER` | `true`             | Prefer the focused window's player   |

## Architecture

```
gesture_media_control/
├── config.py      # frozen Config dataclass + env loading
├── intents.py     # Intent enum + IntentMatcher (pure)
├── focus.py       # FocusDetector: focused-window -> player hint
├── players.py     # PlayerBackend Protocol + PlayerctlBackend + PlayerResolver
├── voice.py       # VoiceCommandRecognizer (injectable model/stream)
├── state.py       # thread-safe AppState
├── controller.py  # MediaController orchestration
├── cli.py         # argument parsing, banner, REPL
└── app.py         # dependency wiring
```

External integrations (subprocess, audio stream, Vosk model) are wrapped behind
small interfaces and injected, so the core logic can be unit tested without a
microphone or media player.

## Testing

```bash
pytest
ruff check .
```
