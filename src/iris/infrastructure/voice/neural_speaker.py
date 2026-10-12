import asyncio
import collections
import logging
import queue
import re
import threading
from collections.abc import Callable, Iterable

import edge_tts
import miniaudio
import numpy
import sounddevice

log = logging.getLogger(__name__)

LevelCallback = Callable[[float], None]


def trim_silence(samples: numpy.ndarray, threshold: int = 300, margin: int = 1200) -> numpy.ndarray:
    loud = numpy.flatnonzero(numpy.abs(samples) > threshold)
    if not loud.size:
        return samples[:0]
    return samples[max(0, loud[0] - margin) : loud[-1] + margin]


SPOKEN_NOISE = re.compile("[\U0001f000-\U0001faff☀-➿️*_#`~>|]")


def clean_for_speech(text: str) -> str:
    return re.sub(r"\s+", " ", SPOKEN_NOISE.sub("", text)).strip()


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text) if part.strip()]
    return parts or [text]


class ContinuousPlayer:
    def __init__(self, sample_rate: int, device: str | None):
        self._chunks: collections.deque[numpy.ndarray] = collections.deque()
        self._lock = threading.Lock()
        self.pending = 0
        self.level = 0.0
        self.volume = 1.0
        self._stream = sounddevice.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=device,
            blocksize=sample_rate // 50,
            callback=self._fill,
        )
        self._stream.start()

    def _fill(self, outdata, frames, time_info, status) -> None:
        out = numpy.zeros(frames, dtype=numpy.int16)
        filled = 0
        with self._lock:
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                take = min(chunk.size, frames - filled)
                out[filled : filled + take] = chunk[:take]
                if take == chunk.size:
                    self._chunks.popleft()
                else:
                    self._chunks[0] = chunk[take:]
                filled += take
            self.pending = max(0, self.pending - filled)
        if self.volume < 1.0:
            out = (out.astype(numpy.float32) * self.volume).astype(numpy.int16)
        played = out[:filled].astype(numpy.float32)
        self.level = min(1.0, float(numpy.sqrt(numpy.mean(played * played))) / 5000) if filled else 0.0
        outdata[:, 0] = out

    def enqueue(self, samples: numpy.ndarray) -> None:
        with self._lock:
            self._chunks.append(samples)
            self.pending += samples.size

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self.pending = 0


class NeuralSpeaker:
    def __init__(
        self,
        voice: str = "pt-BR-ThalitaMultilingualNeural",
        fallback=None,
        sample_rate: int = 24000,
        device: str | None = None,
        rate: str = "+8%",
    ):
        self.device = device
        self.rate = rate
        self.voice = voice
        self.fallback = fallback
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._interrupted = threading.Event()
        self._player: ContinuousPlayer | None = None

    def player(self) -> ContinuousPlayer:
        if self._player is None:
            self._player = ContinuousPlayer(self.sample_rate, self.device)
        return self._player

    def duck(self, volume: float) -> None:
        self.player().volume = volume

    def interrupt(self) -> None:
        self._interrupted.set()
        if self._player is not None:
            self._player.clear()

    async def _stream(self, text: str) -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, self.voice, rate=self.rate).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    def synthesize(self, text: str) -> bytes:
        text = clean_for_speech(text).lstrip(".,;:!?…-– ")
        if not any(c.isalnum() for c in text):
            return bytes(480)
        for attempt in range(3):
            try:
                mp3 = asyncio.run(self._stream(text))
                break
            except Exception:
                if attempt == 2:
                    raise
                log.warning("Neural voice attempt %d failed, retrying", attempt + 1)
                threading.Event().wait(0.4 * (attempt + 1))
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=self.sample_rate)
        return decoded.samples.tobytes()

    def say(self, text: str, on_level: LevelCallback | None = None) -> None:
        self.speak_stream(split_sentences(text), on_level=on_level)

    def speak_stream(self, sentences: Iterable[str], on_level: LevelCallback | None = None, on_start=None) -> None:
        with self._lock:
            self._interrupted.clear()
            self.player().volume = 1.0
            clips: queue.Queue[bytes | None] = queue.Queue()
            spoken_text: list[str] = []

            def produce():
                try:
                    for sentence in sentences:
                        if self._interrupted.is_set():
                            break
                        spoken_text.append(sentence)
                        clips.put(self.synthesize(sentence))
                except Exception:
                    log.exception("Neural voice unavailable")
                    clips.put(b"")
                clips.put(None)

            threading.Thread(target=produce, daemon=True).start()
            player = self.player()
            started = False
            producing = True
            while producing or player.pending:
                if self._interrupted.is_set():
                    player.clear()
                    break
                try:
                    clip = clips.get(timeout=0.05)
                except queue.Empty:
                    clip = False
                if clip is None:
                    producing = False
                elif clip == b"":
                    if not started and self.fallback:
                        self.fallback.say(re.sub(r"[.!?…;:]+", ",", clean_for_speech(" ".join(spoken_text))))
                    producing = False
                elif clip:
                    samples = trim_silence(numpy.frombuffer(clip, dtype=numpy.int16))
                    if samples.size:
                        if not started and on_start:
                            on_start()
                        started = True
                        player.enqueue(samples)
                if on_level:
                    on_level(player.level)
            if on_level:
                on_level(0.0)
