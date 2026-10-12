import array
import json
import math
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import sounddevice
import vosk

LevelCallback = Callable[[float], None]
PartialCallback = Callable[[str], None]


def rms_level(data: bytes) -> float:
    samples = array.array("h", data)
    if not samples:
        return 0.0
    mean_square = sum(s * s for s in samples) / len(samples)
    return min(1.0, math.sqrt(mean_square) / 6000)


class VoskSpeechRecognizer:
    def __init__(self, model_dir: Path, sample_rate: int = 16000, block_size: int = 1600, transcriber=None):
        if not model_dir.exists():
            raise FileNotFoundError(f"Vosk model not found at {model_dir}; run scripts/setup-voice.ps1")
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(str(model_dir))
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.transcriber = transcriber

    def _refine(self, rough: str, utterance: bytes) -> str:
        if not self.transcriber or not utterance:
            return rough
        try:
            return self.transcriber.transcribe(utterance) or rough
        except Exception:
            return rough

    def transcripts(
        self,
        stop: threading.Event | None = None,
        on_level: LevelCallback | None = None,
        on_partial: PartialCallback | None = None,
        silence_timeout: float | None = None,
        grammar: list[str] | None = None,
    ) -> Iterator[str]:
        audio: queue.Queue[bytes] = queue.Queue()
        if grammar:
            recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, json.dumps(grammar))
        else:
            recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        last_partial = ""
        started = time.monotonic()
        utterance = bytearray()

        def on_audio(data, frames, time_info, status):
            audio.put(bytes(data))

        with sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            dtype="int16",
            channels=1,
            callback=on_audio,
        ):
            while stop is None or not stop.is_set():
                try:
                    chunk = audio.get(timeout=0.3)
                except queue.Empty:
                    continue
                if on_level:
                    on_level(rms_level(chunk))
                utterance.extend(chunk)
                if recognizer.AcceptWaveform(chunk):
                    text = json.loads(recognizer.Result()).get("text", "")
                    last_partial = ""
                    if text:
                        started = time.monotonic()
                        yield self._refine(text, bytes(utterance))
                    utterance.clear()
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "")
                    if partial and partial != last_partial:
                        last_partial = partial
                        started = time.monotonic()
                        if on_partial:
                            on_partial(partial)
                if silence_timeout and not last_partial and time.monotonic() - started > silence_timeout:
                    return

    def listen_once(
        self,
        on_level: LevelCallback | None = None,
        on_partial: PartialCallback | None = None,
        silence_timeout: float | None = 8.0,
    ) -> str:
        stream = self.transcripts(on_level=on_level, on_partial=on_partial, silence_timeout=silence_timeout)
        try:
            return next(stream, "")
        finally:
            stream.close()

    def wake_phrases(
        self, grammar: list[str], stop: threading.Event | None = None, on_level: LevelCallback | None = None
    ) -> Iterator[tuple[str, str]]:
        audio: queue.Queue[bytes] = queue.Queue()
        spotter = vosk.KaldiRecognizer(self.model, self.sample_rate, json.dumps(grammar))
        transcriber = vosk.KaldiRecognizer(self.model, self.sample_rate)

        def on_audio(data, frames, time_info, status):
            audio.put(bytes(data))

        with sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            dtype="int16",
            channels=1,
            callback=on_audio,
        ):
            spotted = ""
            utterance = bytearray()
            while stop is None or not stop.is_set():
                try:
                    chunk = audio.get(timeout=0.3)
                except queue.Empty:
                    continue
                if on_level:
                    on_level(rms_level(chunk))
                utterance.extend(chunk)
                if spotter.AcceptWaveform(chunk):
                    spotted = json.loads(spotter.Result()).get("text", "") or spotted
                if transcriber.AcceptWaveform(chunk):
                    full = json.loads(transcriber.Result()).get("text", "")
                    final = json.loads(spotter.FinalResult()).get("text", "")
                    spotted = final or spotted
                    if spotted.replace("[unk]", "").strip():
                        yield spotted, self._refine(full, bytes(utterance))
                    spotted = ""
                    utterance.clear()
