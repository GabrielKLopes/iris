from iris.application.intent import KeywordIntentClassifier
from iris.application.voice_launcher import VoiceLauncher


class FakeRecognizer:
    def __init__(self, texts):
        self.texts = texts

    def transcripts(self):
        yield from self.texts


class FakeLauncher:
    def __init__(self):
        self.opened = 0

    def open_or_focus(self):
        self.opened += 1


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_opens_app_on_open_intent():
    launcher = FakeLauncher()
    VoiceLauncher(FakeRecognizer(["bom dia", "abre a iris"]), KeywordIntentClassifier(), launcher).run()
    assert launcher.opened == 1


def test_cooldown_ignores_repeated_commands():
    launcher = FakeLauncher()
    clock = FakeClock()
    voice = VoiceLauncher(FakeRecognizer([]), KeywordIntentClassifier(), launcher, cooldown_seconds=5, clock=clock)
    assert voice.handle("abre a iris")
    clock.now = 2
    assert not voice.handle("abre a iris")
    clock.now = 6
    assert voice.handle("abre a iris")
    assert launcher.opened == 2
