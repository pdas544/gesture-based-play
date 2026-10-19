import os
import queue
import json
import shutil
import subprocess
import threading
from datetime import datetime
import re

try:
    import sounddevice as sd
    SOUNDDEVICE_READY = True
    SOUNDDEVICE_IMPORT_ERROR = ""
except Exception as error:
    sd = None
    SOUNDDEVICE_READY = False
    SOUNDDEVICE_IMPORT_ERROR = str(error)

try:
    from vosk import Model, KaldiRecognizer, SetLogLevel
    VOSK_READY = True
    VOSK_IMPORT_ERROR = ""
except Exception as error:
    Model = None
    KaldiRecognizer = None
    SetLogLevel = None
    VOSK_READY = False
    VOSK_IMPORT_ERROR = str(error)

# ========== CONFIGURATION ==========
PLAYERCTL_PATH = shutil.which("playerctl")
PLAYERCTL_HINT_SHOWN = False
last_playerctl_target = None
runtime_player_override = None

VOSK_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "models",
    "vosk-model-small-en-us-0.15",
)
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_BLOCK_SIZE = 800  # Reduced from 4000 for lower latency (~50ms vs 250ms)
TRANSITION_GUARD_SECONDS = 0.5  # Prevent rapid-fire duplicate commands
PREFERRED_PLAYER = None
PREFER_FOCUSED_PLAYER = True

# Voice command mappings: list of recognized phrases for each intent.
VOICE_COMMANDS = {
    "PLAY": ["play", "resume", "start", "continue", "begin"],
    "PAUSE": ["pause", "stop", "halt", "hold", "wait"],
    "NEXT": ["next", "skip", "forward", "advance"],
    "PREVIOUS": ["previous", "back", "backward", "rewind", "go back"],
    "VOLUME_UP": ["volume up", "louder", "increase volume", "turn up", "turn it up"],
    "VOLUME_DOWN": ["volume down", "quieter", "decrease volume", "turn down", "turn it down", "softer"],
}

# Map of voice intent -> playerctl argument (or custom tuple for volume).
PLAYERCTL_INTENT_MAP = {
    "PLAY": "play",
    "PAUSE": "pause",
    "NEXT": "next",
    "PREVIOUS": "previous",
    "VOLUME_UP": ("volume", "0.1+"),
    "VOLUME_DOWN": ("volume", "0.1-"),
}

# ========== STATE TRACKING ==========
last_action_time = 0
last_triggered_intent = None
current_state = "Idle"  # Display state: Playing / Paused / Idle


# ========== PLAYERCTL HELPERS ==========
def run_playerctl_command(arguments):
    """Run a playerctl command and return the completed process."""
    return subprocess.run(
        [PLAYERCTL_PATH, *arguments],
        capture_output=True,
        text=True,
    )


def list_playerctl_players():
    """Return the currently available MPRIS player names."""
    if not PLAYERCTL_PATH:
        return []

    result = run_playerctl_command(["-l"])
    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_player_status(player_name):
    """Return playerctl status for a specific player, or None on failure."""
    result = run_playerctl_command([f"--player={player_name}", "status"])
    if result.returncode != 0:
        return None

    return result.stdout.strip()


def _parse_gnome_eval_output(raw_output):
    """Parse org.gnome.Shell.Eval output and return focused app wm_class hint."""
    text = raw_output.strip()
    if not text.startswith("("):
        return None

    first_quote = text.find("'")
    last_quote = text.rfind("'")
    if first_quote == -1 or last_quote == -1 or last_quote <= first_quote:
        return None

    value = text[first_quote + 1:last_quote].strip().lower()
    return value or None


def get_focused_player_hint():
    """Try to read focused app name and map it to an MPRIS player name substring."""
    gnome_result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.Shell",
            "--object-path",
            "/org/gnome/Shell",
            "--method",
            "org.gnome.Shell.Eval",
            "global.display.focus_window ? global.display.focus_window.wm_class.toLowerCase() : ''",
        ],
        capture_output=True,
        text=True,
    )
    if gnome_result.returncode == 0:
        hint = _parse_gnome_eval_output(gnome_result.stdout)
        if hint:
            return hint

    xdotool_path = shutil.which("xdotool")
    if xdotool_path:
        x11_result = subprocess.run(
            [xdotool_path, "getactivewindow", "getwindowclassname"],
            capture_output=True,
            text=True,
        )
        if x11_result.returncode == 0:
            value = x11_result.stdout.strip().lower()
            return value or None

    return None


def resolve_playerctl_target(intent):
    """Choose the best MPRIS player to control for the requested intent."""
    global last_playerctl_target

    players = list_playerctl_players()
    if not players:
        return None

    if runtime_player_override in players:
        return runtime_player_override

    if PREFERRED_PLAYER in players:
        return PREFERRED_PLAYER

    if PREFER_FOCUSED_PLAYER:
        focused_hint = get_focused_player_hint()
        if focused_hint:
            focused_matches = [
                player_name
                for player_name in players
                if focused_hint in player_name.lower() or player_name.lower() in focused_hint
            ]
            if len(focused_matches) == 1:
                return focused_matches[0]

    if intent in ("PLAY", "PAUSE", "NEXT", "PREVIOUS") and last_playerctl_target in players:
        return last_playerctl_target

    player_statuses = {}
    for player_name in players:
        status = get_player_status(player_name)
        if status:
            player_statuses[player_name] = status

    if intent in ("PAUSE", "NEXT", "PREVIOUS"):
        playing_players = [
            player_name
            for player_name, status in player_statuses.items()
            if status == "Playing"
        ]
        if len(playing_players) == 1:
            return playing_players[0]
        if last_playerctl_target in playing_players:
            return last_playerctl_target
    elif intent == "PLAY":
        paused_players = [
            player_name
            for player_name, status in player_statuses.items()
            if status == "Paused"
        ]
        if len(paused_players) == 1:
            return paused_players[0]
        if last_playerctl_target in paused_players:
            return last_playerctl_target

    if len(players) == 1:
        return players[0]

    if last_playerctl_target in players:
        return last_playerctl_target

    return None


def trigger_media_action(intent):
    """Send a media control command to the best matching player via playerctl."""
    global last_playerctl_target, current_state

    if not PLAYERCTL_PATH:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Cannot send {intent}: playerctl is not installed."
        )
        if not PLAYERCTL_HINT_SHOWN:
            print("Install playerctl for Linux media control: sudo apt install playerctl")
            PLAYERCTL_HINT_SHOWN = True
        return False

    target_player = resolve_playerctl_target(intent)
    if not target_player:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  No unambiguous media player found for {intent}."
        )
        print("Pause other players or start playback in the player you want to control.")
        return False

    action = PLAYERCTL_INTENT_MAP.get(intent)
    if action is None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Unknown intent: {intent}")
        return False

    if isinstance(action, tuple):
        arguments = [f"--player={target_player}", action[0], action[1]]
        action_label = f"{action[0]} {action[1]}"
    else:
        arguments = [f"--player={target_player}", action]
        action_label = action

    result = run_playerctl_command(arguments)
    if result.returncode != 0:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ❌ playerctl failed for {intent} on {target_player}: {result.stderr.strip()}"
        )
        return False

    last_playerctl_target = target_player

    # Update display state based on intent.
    if intent == "PLAY":
        current_state = "Playing"
    elif intent == "PAUSE":
        current_state = "Paused"

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 🎤 {intent} → {target_player} ({action_label})"
    )
    return True


# ========== VOICE RECOGNITION ==========
class VoiceCommandRecognizer:
    """Capture audio from the default microphone and emit recognized intents."""

    def __init__(self, model_path, on_intent):
        self._model_path = model_path
        self._on_intent = on_intent
        self._audio_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._stream = None
        self._recognizer = None
        self._thread = None

    def _audio_callback(self, indata, _frames, _time_info, status):
        if status:
            pass
        self._audio_queue.put(bytes(indata))

    def _process_loop(self):
        if SetLogLevel is not None:
            SetLogLevel(-1)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎙️  Loading Vosk model from {self._model_path}...")
        try:
            model = Model(self._model_path)
        except Exception as error:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to load Vosk model: {error}")
            return

        self._recognizer = KaldiRecognizer(model, SAMPLE_RATE)

        # Use grammar-constrained recognition for improved accuracy on our specific command phrases.
        # Import json here for local use in this method scope.
        _json = json

        # Restrict recognition to our known command phrases.
        all_phrases = []
        for phrases in VOICE_COMMANDS.values():
            all_phrases.extend(phrases)
        grammar_json = _json.dumps(all_phrases)
        self._recognizer.SetGrammar(grammar_json)
        # This restricts the search space to only our known commands, dramatically improving
        # detection of short words like "pause" that the small model may otherwise miss.
        all_phrases = []
        for phrases in VOICE_COMMANDS.values():
            all_phrases.extend(phrases)
        grammar_json = _json.dumps(all_phrases)
        self._recognizer.SetGrammar(grammar_json)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Voice recognition ready. Listening for commands...")

        while not self._stop_event.is_set():
            try:
                data = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Process audio through the recogniser.
            self._recognizer.AcceptWaveform(data)

            # Check partial results for faster detection.
            partial = _json.loads(self._recognizer.PartialResult())
            partial_text = partial.get("partial", "").strip().lower()
            if partial_text:
                intent = match_phrase_to_intent(partial_text)
                if intent:
                    self._handle_phrase(partial_text, is_partial=True)

            # Check final results.
            if self._recognizer.AcceptWaveform(data):
                result = _json.loads(self._recognizer.Result())
                text = result.get("text", "").strip().lower()
                if text:
                    self._handle_phrase(text, is_partial=False)

        final_result = _json.loads(self._recognizer.FinalResult())
        text = final_result.get("text", "").strip().lower()
        if text:
            self._handle_phrase(text, is_partial=False)

    def _handle_phrase(self, text, is_partial=False):
        """Match recognized text to a known intent and invoke the callback."""
        intent = match_phrase_to_intent(text)
        if intent:
            self._on_intent(intent, text, is_partial)

    def start(self):
        """Open the audio stream and start the recognition thread."""
        if not (VOSK_READY and SOUNDDEVICE_READY):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Voice recognition dependencies are missing.")
            if not VOSK_READY:
                print(f"   vosk: {VOSK_IMPORT_ERROR}")
            if not SOUNDDEVICE_READY:
                print(f"   sounddevice: {SOUNDDEVICE_IMPORT_ERROR}")
            return False

        if not os.path.isdir(self._model_path):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Vosk model not found at {self._model_path}")
            print("Download the model and unpack it into the models/ directory.")
            return False

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=AUDIO_BLOCK_SIZE,
                dtype="int16",
                channels=CHANNELS,
                callback=self._audio_callback,
            )
        except Exception as error:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to open microphone: {error}")
            return False

        self._stream.start()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop the recognition thread and close the audio stream."""
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)


def match_phrase_to_intent(text):
    """Map a recognized phrase to one of the supported intents.

    Uses regex word-boundary matching to avoid false positives (e.g. "pause"
    in "because") and prioritizes longer composite phrases first (e.g. "volume up"
    before "volume").
    """
    if not text:
        return None

    normalized = " ".join(text.split()).lower()

    # Sort intents by their longest phrase length (descending) so composite
    # phrases like "volume up" are matched before single words like "volume".
    sorted_intents = sorted(
        VOICE_COMMANDS.items(),
        key=lambda item: max(len(p) for p in item[1]),
        reverse=True,
    )

    for intent, phrases in sorted_intents:
        for phrase in phrases:
            if re.search(r"\b" + re.escape(phrase) + r"\b", normalized):
                return intent

    return None


# ========== CONSOLE STATUS DISPLAY ==========
def render_status():
    """Print a single-line status update (used after each state change)."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    target_label = runtime_player_override or PREFERRED_PLAYER or (last_playerctl_target or "auto")
    last_intent = last_triggered_intent or "—"
    print(
        f"[{timestamp}] State: {current_state} | Last command: {last_intent} | Target: {target_label}"
    )


# ========== MAIN ENTRY POINT ==========
def main():
    global last_action_time, last_triggered_intent, runtime_player_override, current_state

    print("=" * 60)
    print("🎤 Voice Media Controller - Ready")
    print("=" * 60)
    print("Voice commands (English):")
    print("  • 'play' / 'resume'         → Start playback")
    print("  • 'pause' / 'stop'          → Pause playback")
    print("  • 'next' / 'skip'           → Next track")
    print("  • 'previous' / 'back'       → Previous track")
    print("  • 'volume up' / 'louder'    → Increase volume")
    print("  • 'volume down' / 'softer'  → Decrease volume")
    print()
    print("Keyboard controls:")
    print("  • 't' → cycle target player")
    print("  • 'q' → quit")
    print("  • Ctrl+C → quit")
    print("=" * 60)

    if not PLAYERCTL_PATH:
        print("⚠️  playerctl not found. Install it for media control: sudo apt install playerctl")
    if PREFERRED_PLAYER:
        print(f"Preferred player: {PREFERRED_PLAYER}")
    if PREFER_FOCUSED_PLAYER:
        print("Focused player detection: enabled (GNOME/Wayland + X11 fallback)")

    # Discover available players once at startup.
    initial_players = list_playerctl_players()
    if initial_players:
        print(f"Available players: {', '.join(initial_players)}")
    else:
        print("No MPRIS players detected yet. Open a media player and try again.")

    print("=" * 60)

    def on_voice_intent(intent, recognized_text="", is_partial=False):
        """Callback invoked from the voice recognition thread."""
        global last_action_time, last_triggered_intent

        now = datetime.now().timestamp()
        if intent == last_triggered_intent and (now - last_action_time) < TRANSITION_GUARD_SECONDS:
            # Suppress rapid duplicate commands without bothering the user.
            return

        success = trigger_media_action(intent)
        if success:
            last_action_time = now
            last_triggered_intent = intent
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Recognized: \"{recognized_text}\" ({'partial' if is_partial else 'final'})")
            render_status()

    recognizer = VoiceCommandRecognizer(VOSK_MODEL_PATH, on_voice_intent)
    if not recognizer.start():
        print("Voice recognition could not start. Press 'q' to quit.")

    print("Listening for voice commands. Speak clearly into your microphone.")
    print()

    try:
        while True:
            try:
                line = input("> ").strip().lower()
            except EOFError:
                break

            if line == "q":
                break
            elif line == "t":
                players = list_playerctl_players()
                if players:
                    if runtime_player_override not in players:
                        runtime_player_override = players[0]
                    else:
                        next_index = (players.index(runtime_player_override) + 1) % len(players)
                        runtime_player_override = players[next_index]
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 Runtime target set to: {runtime_player_override}"
                    )
                    render_status()
                else:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  No playerctl players found to cycle"
                    )
            elif line == "status":
                render_status()
            elif line == "players":
                players = list_playerctl_players()
                if players:
                    for player in players:
                        status = get_player_status(player) or "unknown"
                        print(f"  • {player} ({status})")
                else:
                    print("No MPRIS players detected.")
            elif line in ("help", "?"):
                print("Commands: t (cycle target), players (list), status, q (quit)")
            elif line:
                print(f"Unknown command: {line!r}. Type 'help' for available commands.")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        recognizer.stop()
        print("👋 Exiting... Goodbye!")


if __name__ == "__main__":
    main()
