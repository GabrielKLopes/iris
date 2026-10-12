from collections.abc import Iterator
from typing import Protocol

from iris.domain.intents import Intent


class SpeechRecognizer(Protocol):
    def transcripts(self) -> Iterator[str]: ...


class IntentClassifier(Protocol):
    def classify(self, text: str) -> Intent: ...


class AppLauncher(Protocol):
    def open_or_focus(self) -> None: ...
