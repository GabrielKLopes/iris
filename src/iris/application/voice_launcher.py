import logging
import time
from collections.abc import Callable

from iris.application.ports import AppLauncher, IntentClassifier, SpeechRecognizer
from iris.domain.intents import Intent

logger = logging.getLogger(__name__)


class VoiceLauncher:
    def __init__(
        self,
        recognizer: SpeechRecognizer,
        classifier: IntentClassifier,
        launcher: AppLauncher,
        cooldown_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.recognizer = recognizer
        self.classifier = classifier
        self.launcher = launcher
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._last_trigger: float | None = None

    def run(self) -> None:
        for text in self.recognizer.transcripts():
            self.handle(text)

    def handle(self, text: str) -> bool:
        if self.classifier.classify(text) is not Intent.OPEN_APP:
            return False
        now = self.clock()
        if self._last_trigger is not None and now - self._last_trigger < self.cooldown_seconds:
            return False
        self._last_trigger = now
        logger.info("Opening app from voice command: %s", text)
        self.launcher.open_or_focus()
        return True
