import re
import threading

import pyttsx3


class WindowsSpeaker:
    def __init__(self, rate: int = 185):
        self.rate = rate
        self._lock = threading.Lock()
        self.voice_id = self._pick_portuguese_voice()

    def _pick_portuguese_voice(self) -> str | None:
        engine = pyttsx3.init()
        try:
            for voice in engine.getProperty("voices"):
                description = f"{voice.id} {voice.name} {voice.languages}".lower()
                if "pt-br" in description or "portuguese" in description or "maria" in description:
                    return voice.id
            return None
        finally:
            engine.stop()

    def say(self, text: str, on_level=None) -> None:
        with self._lock:
            engine = pyttsx3.init()
            if self.voice_id:
                engine.setProperty("voice", self.voice_id)
            engine.setProperty("rate", self.rate)
            engine.say(re.sub(r"[.!?…;:]+", ",", text))
            engine.runAndWait()
            engine.stop()
