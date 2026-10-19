"""Microphone capture and the recognition worker thread.

Responsibilities are deliberately narrow: pull audio frames, feed them to an
injected :class:`SpeechEngine`, and forward transcriptions to a callback. The
engine and audio stream are factories so tests can run without Vosk or a
microphone.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

from .config import Config
from .speech import SpeechEngine

logger = logging.getLogger(__name__)

PhraseCallback = Callable[[str, bool], None]
FrameCallback = Callable[[bytes], None]


class AudioStream(Protocol):
    """Minimal subset of ``sounddevice.RawInputStream`` used here."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


EngineFactory = Callable[[], SpeechEngine]
StreamFactory = Callable[["VoiceCommandRecognizer"], AudioStream]


def default_engine_factory(config: Config, phrases: list[str]) -> EngineFactory:
    """Build the production Vosk engine factory for ``config``."""

    def factory() -> SpeechEngine:
        from .speech import VoskEngine

        return VoskEngine.create(config.model_path, phrases, config.sample_rate)

    return factory


def default_stream_factory(config: Config) -> StreamFactory:
    """Build the production ``sounddevice`` stream factory for ``config``."""

    def factory(recognizer: VoiceCommandRecognizer) -> AudioStream:
        import sounddevice as sd

        return sd.RawInputStream(
            samplerate=config.sample_rate,
            blocksize=config.audio_block_size,
            dtype="int16",
            channels=config.channels,
            callback=recognizer.audio_callback,
        )

    return factory


class VoiceCommandRecognizer:
    """Capture microphone audio and emit recognized phrases."""

    def __init__(
        self,
        config: Config,
        on_phrase: PhraseCallback,
        *,
        engine_factory: EngineFactory,
        stream_factory: StreamFactory,
        on_frame: FrameCallback | None = None,
        stop_timeout: float = 2.0,
    ) -> None:
        self._config = config
        self._on_phrase = on_phrase
        self._on_frame = on_frame
        self._engine_factory = engine_factory
        self._stream_factory = stream_factory
        self._stop_timeout = stop_timeout

        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._stop_event = threading.Event()
        self._engine: SpeechEngine | None = None
        self._stream: AudioStream | None = None
        self._thread: threading.Thread | None = None

    def audio_callback(self, indata, _frames, _time_info, _status) -> None:
        """sounddevice callback: enqueue raw audio bytes."""
        self._audio_queue.put(bytes(indata))

    def start(self) -> bool:
        """Prepare the engine and microphone, then start the worker thread."""
        if not self._config.model_path.is_dir():
            logger.error("Vosk model not found at %s", self._config.model_path)
            logger.info("Download a model and unpack it into the models/ directory.")
            return False

        try:
            self._engine = self._engine_factory()
        except ImportError as error:
            logger.error("Speech dependencies are missing: %s", error)
            return False
        except Exception as error:  # model load failures
            logger.error("Failed to load the speech engine: %s", error)
            return False

        try:
            self._stream = self._stream_factory(self)
        except ImportError as error:
            logger.error("Audio dependencies are missing: %s", error)
            return False
        except Exception as error:
            logger.error("Failed to open the microphone: %s", error)
            return False

        self._stream.start()
        self._thread = threading.Thread(
            target=self._process_loop, name="voice-recognizer", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal shutdown, release the stream, and join the worker."""
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # best-effort cleanup
                logger.debug("Error closing audio stream", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=self._stop_timeout)

    def _process_loop(self) -> None:
        assert self._engine is not None
        engine = self._engine
        logger.info("Voice recognition ready. Listening for commands...")

        while not self._stop_event.is_set():
            try:
                data = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._on_frame is not None:
                self._on_frame(data)
            for recognition in engine.ingest(data):
                self._on_phrase(recognition.text, recognition.is_partial)

        for recognition in engine.finalize():
            self._on_phrase(recognition.text, recognition.is_partial)
