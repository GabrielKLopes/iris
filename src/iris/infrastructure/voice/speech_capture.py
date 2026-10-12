import array
import collections
import logging
import math
import queue
import threading
import time
from collections.abc import Callable, Iterator

import sounddevice

log = logging.getLogger(__name__)

LevelCallback = Callable[[float], None]


def frame_rms(data: bytes) -> float:
    samples = array.array("h", data)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def find_input_device(name: str | None) -> int | None:
    if not name:
        return None
    wanted = name.lower()
    for index, device in enumerate(sounddevice.query_devices()):
        if device["max_input_channels"] > 0 and wanted in device["name"].lower():
            return index
    log.warning("Input device %r not found, using the system default", name)
    return None


class SpeechCapture:
    def __init__(
        self,
        transcriber,
        device: str | None = None,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        preroll_seconds: float = 0.6,
        end_silence_seconds: float = 1.0,
        max_utterance_seconds: float = 20.0,
    ):
        self.transcriber = transcriber
        self.device = find_input_device(device)
        self.sample_rate = sample_rate
        self.frame_size = sample_rate * frame_ms // 1000
        self.frame_seconds = frame_ms / 1000
        self.preroll_frames = int(preroll_seconds / self.frame_seconds)
        self.end_silence_frames = int(end_silence_seconds / self.frame_seconds)
        self.max_frames = int(max_utterance_seconds / self.frame_seconds)
        self.noise_floor = 60.0
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=2000)
        self._stream = None
        self._lock = threading.Lock()

    def _ensure_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                return

            def on_audio(data, frames, time_info, status):
                try:
                    self._frames.put_nowait(bytes(data))
                except queue.Full:
                    pass

            self._stream = sounddevice.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.frame_size,
                dtype="int16",
                channels=1,
                device=self.device,
                callback=on_audio,
            )
            self._stream.start()
            name = sounddevice.query_devices(self._stream.device)["name"]
            log.info("Microphone open: %s", name)

    def _recent_frames(self) -> collections.deque:
        recent: collections.deque = collections.deque(maxlen=self.preroll_frames)
        while True:
            try:
                recent.append(self._frames.get_nowait())
            except queue.Empty:
                return recent

    def level(self, rms: float) -> float:
        floor = max(self.noise_floor, 20.0)
        return max(0.0, min(1.0, (20 * math.log10(max(rms, 1.0) / (floor * 1.5))) / 30))

    def utterances(
        self,
        stop: threading.Event | None = None,
        on_level: LevelCallback | None = None,
        timeout: float | None = None,
        on_onset: Callable[[], None] | None = None,
        onset_frames: int = 12,
        sensitivity: float = 1.0,
    ) -> Iterator[bytes]:
        self._ensure_stream()
        preroll = self._recent_frames()
        speech: list[bytes] = []
        loud_run = 0
        quiet_run = 0
        loud_frames = 0
        signaled = False
        started = time.monotonic()
        while stop is None or not stop.is_set():
            try:
                frame = self._frames.get(timeout=0.3)
            except queue.Empty:
                continue
            rms = frame_rms(frame)
            if on_level:
                on_level(self.level(rms))
            threshold = max(self.noise_floor * 3.0, 120.0) * sensitivity
            if not speech:
                preroll.append(frame)
                if rms > threshold:
                    loud_run += 1
                else:
                    loud_run = 0
                    self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
                if loud_run >= 3:
                    speech = list(preroll)
                    quiet_run = 0
                elif timeout and time.monotonic() - started > timeout:
                    return
                continue
            speech.append(frame)
            if rms >= threshold * 0.6:
                loud_frames += 1
                if on_onset and not signaled and loud_frames >= onset_frames:
                    signaled = True
                    on_onset()
            quiet_run = quiet_run + 1 if rms < threshold * 0.6 else 0
            if quiet_run >= self.end_silence_frames or len(speech) >= self.max_frames:
                yield b"".join(speech)
                speech, loud_run, loud_frames, signaled = [], 0, 0, False
                preroll.clear()
                started = time.monotonic()

    def phrases(self, stop: threading.Event | None = None, on_level: LevelCallback | None = None) -> Iterator[str]:
        for utterance in self.utterances(stop=stop, on_level=on_level):
            text = self.transcriber.transcribe(utterance)
            log.info("Phrase (%.1fs): %r", len(utterance) / 2 / self.sample_rate, text)
            if text:
                yield text

    def listen_once(self, on_level: LevelCallback | None = None, silence_timeout: float = 8.0) -> str:
        stream = self.utterances(on_level=on_level, timeout=silence_timeout)
        try:
            for utterance in stream:
                text = self.transcriber.transcribe(utterance)
                log.info("Utterance (%.1fs): %r", len(utterance) / 2 / self.sample_rate, text)
                if text:
                    return text
                return ""
            return ""
        finally:
            stream.close()
