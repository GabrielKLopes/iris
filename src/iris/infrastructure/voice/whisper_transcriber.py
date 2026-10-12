import logging
import threading
from pathlib import Path

import numpy

log = logging.getLogger(__name__)

HALLUCINATIONS = ("amara.org", "legendas pela comunidade", "inscreva-se", "obrigado por assistir", "legenda adriana")


class WhisperTranscriber:
    def __init__(self, model_size: str, download_root: Path, language: str = "pt", hint: str = "Iris, bom dia, boa tarde, boa noite. Abre o Chrome, o Teams, o VS Code, o WhatsApp, o Spotify, o Outlook, o Excel. Azure DevOps, Docker, Kubernetes, Keycloak."):
        self.model_size = model_size
        self.download_root = download_root
        self.language = language
        self.hint = hint
        self._model = None
        self.extra_hint = None
        self._lock = threading.Lock()

    def preload(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self.download_root.mkdir(parents=True, exist_ok=True)
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8", download_root=str(self.download_root))
                log.info("Whisper model %s loaded", self.model_size)
            return self._model

    def _prompt(self) -> str:
        extra = ""
        if self.extra_hint:
            try:
                extra = self.extra_hint() or ""
            except Exception:
                extra = ""
        return f"{self.hint} {extra}".strip()[-800:]

    def transcribe(self, pcm: bytes) -> str:
        audio = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32) / 32768
        peak = float(numpy.abs(audio).max()) if audio.size else 0.0
        if peak < 0.003:
            return ""
        audio = audio * (0.9 / peak)
        segments, _ = self._load().transcribe(
            audio,
            language=self.language,
            beam_size=1,
            initial_prompt=self._prompt(),
            condition_on_previous_text=False,
            vad_filter=False,
        )
        texts = [s.text for s in segments if s.no_speech_prob < 0.5 and s.avg_logprob > -0.9]
        text = "".join(texts).strip()
        if any(marker in text.lower() for marker in HALLUCINATIONS):
            return ""
        return text
