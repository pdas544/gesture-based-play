# Voice Media Control

Control Linux media playback with your voice. Speech is transcribed offline with
[Vosk](https://alphacephei.com/vosk/) and translated into
[`playerctl`](https://github.com/altdesktop/playerctl) MPRIS commands, so it works
with Spotify, VLC, MPV, browsers, and any other MPRIS-compliant player.

An optional wake word turns it into an always-listening assistant: say
"hey jarvis" (or "hey lenovo" with the Vosk fallback), hear "Hi, how can I help",
then speak your command.

> The repository name mentions "gesture"; the current implementation is
> **voice-only**. Gesture input is not implemented yet.

## Features

- Wake-word gated commands with a 10-second session (extended by each command)
- Spoken greeting via Speech Dispatcher (`spd-say`)
- Offline speech recognition (no cloud calls)
- Grammar-constrained recognition tuned for short command words
- System volume control (`wpctl`/`amixer`/`pactl`) with MPRIS fallback
- Smart player targeting: runtime override → preferred player → focused window →
  playing/paused heuristics
- Duplicate-command suppression
- `--diagnose` to inspect MPRIS capabilities (e.g. players that cannot skip)
- Graceful degradation when optional dependencies or players are missing

## Voice commands

First say the wake word ("hey jarvis"), then one of:

| Intent        | Example phrases                                    |
| ------------- | -------------------------------------------------- |
| Play          | play, resume, start, continue, begin               |
| Pause         | pause, stop, halt, hold, wait                      |
| Next          | next, skip, forward, advance                       |
| Previous      | previous, back, backward, rewind, go back          |
| Volume up     | volume up, louder, increase volume, turn up        |
| Volume down   | volume down, quieter, decrease volume, turn down   |

Say "goodbye", "stop listening", or "never mind" to close the session early, or
wait 10 seconds for it to time out.

## Requirements

- Python 3.10+
- `playerctl` (`sudo apt install playerctl`)
- `spd-say` for the spoken greeting (`sudo apt install speech-dispatcher`)
- A Vosk speech model unpacked into `models/`, e.g.
  `models/vosk-model-small-en-us-0.15/`
- Optional: openWakeWord for accurate "hey jarvis" detection
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

### Wake word (optional)

openWakeWord is not a hard dependency. Without it the app falls back to matching
"hey lenovo" / "ok lenovo" from the Vosk transcript, which works but is less
reliable. To install openWakeWord's ONNX models:

```bash
PYTHON=.venv/bin/python ./scripts/setup-wake.sh
```

The script works around openWakeWord 0.6.0's unusable `tflite-runtime`
dependency (no Python 3.13 wheel) by installing with `--no-deps` and using ONNX.

## Run

```bash
python gesture-media-control.py
# or, after `pip install -e .`
voice-media-control
# or
python -m gesture_media_control
```

Useful flags:

```bash
python -m gesture_media_control --diagnose      # show players and capabilities
python -m gesture_media_control --no-wake       # accept commands without a wake word
python -m gesture_media_control --wake-engine vosk
python -m gesture_media_control --daemon        # headless, for systemd
```

Console commands: `t` cycle target player, `players` list players, `status` show
state, `help` show help, `q` quit, `Ctrl+C` quit.

## Run as a user service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/voice-media-control.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-media-control
journalctl --user -u voice-media-control -f
```

Edit `WorkingDirectory` and `ExecStart` in the unit if the repository is not at
`~/Downloads/personal/gesture-based-play`.

## Configuration

Configuration is read from environment variables (see
`gesture_media_control/config.py`):

| Variable                    | Default               | Description                              |
| --------------------------- | --------------------- | ---------------------------------------- |
| `VMC_MODEL_PATH`            | `models/...`          | Path to the Vosk model directory         |
| `VMC_SAMPLE_RATE`           | `16000`               | Audio sample rate                        |
| `VMC_AUDIO_BLOCK_SIZE`      | `800`                 | Frames per audio block                   |
| `VMC_TRANSITION_GUARD`      | `0.5`                 | Duplicate-command guard (seconds)        |
| `VMC_PREFERRED_PLAYER`      | *(unset)*             | Preferred MPRIS player name              |
| `VMC_PREFER_FOCUSED_PLAYER` | `true`                | Prefer the focused window's player       |
| `VMC_VOLUME_BACKEND`        | `auto`                | `auto`, `system`, or `mpris`             |
| `VMC_VOLUME_STEP`           | `5`                   | Volume step in percent                   |
| `VMC_WAKE_ENABLED`          | `true`                | Enable the wake-word gate                |
| `VMC_WAKE_ENGINE`           | `auto`                | `auto`, `openwakeword`, or `vosk`        |
| `VMC_WAKE_MODELS`           | `hey_jarvis`          | Comma-separated openWakeWord models      |
| `VMC_WAKE_THRESHOLD`        | `0.5`                 | openWakeWord detection threshold         |
| `VMC_WAKE_PHRASES`          | `hey lenovo,ok lenovo`| Vosk fallback wake phrases               |
| `VMC_SESSION_TIMEOUT`       | `10`                  | Command session timeout (seconds)        |
| `VMC_GREETING`              | `Hi, how can I help`  | Spoken greeting                          |
| `VMC_TTS_COMMAND`           | `spd-say`             | Text-to-speech command                   |
| `VMC_TTS_COOLDOWN`          | `0.5`                 | Ignore mic input after speech (seconds)  |

## Architecture

```
gesture_media_control/
├── config.py      # frozen Config dataclass + env loading
├── intents.py     # Intent enum + IntentMatcher (pure)
├── wake.py        # WakeSession + openWakeWord/Vosk wake detectors
├── assistant.py   # wake gating, greeting, session orchestration
├── announce.py    # Announcer + SpeechDispatcherAnnouncer
├── focus.py       # FocusDetector: focused-window -> player hint
├── players.py     # PlayerBackend Protocol + PlayerctlBackend + PlayerResolver
├── volume.py      # system volume backends + MPRIS fallback
├── voice.py       # VoiceCommandRecognizer (injectable model/stream)
├── state.py       # thread-safe AppState
├── controller.py  # MediaController orchestration
├── cli.py         # argument parsing, banner, REPL, daemon mode
└── app.py         # dependency wiring
```

External integrations (subprocess, audio stream, Vosk model, TTS) are wrapped
behind small interfaces and injected, so the core logic can be unit tested
without a microphone or media player.

## Testing

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```
