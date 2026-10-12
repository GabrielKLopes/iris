import ctypes
import logging
import sys
from pathlib import Path

from iris.application.intent import KeywordIntentClassifier
from iris.application.voice_launcher import VoiceLauncher
from iris.config import Settings

MUTEX_NAME = "Local\\IrisVoiceListener"
ERROR_ALREADY_EXISTS = 183

_mutex = None


def _acquire_single_instance() -> bool:
    global _mutex
    kernel32 = ctypes.windll.kernel32
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _app_executable(settings: Settings) -> Path:
    if settings.app_executable:
        return settings.app_executable
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "iris.exe"
    return Path(__file__).resolve().parents[2] / "dist" / "iris.exe"


def _configure_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=settings.log_dir / "listener.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    settings = Settings()
    _configure_logging(settings)
    if not _acquire_single_instance():
        logging.info("Listener already running; exiting")
        return

    from iris.infrastructure.voice.vosk_recognizer import VoskSpeechRecognizer
    from iris.infrastructure.windows.launcher import WindowsAppLauncher

    try:
        launcher = VoiceLauncher(
            recognizer=VoskSpeechRecognizer(settings.voice_model_dir),
            classifier=KeywordIntentClassifier(),
            launcher=WindowsAppLauncher(_app_executable(settings)),
            cooldown_seconds=settings.voice_cooldown_seconds,
        )
        logging.info("Voice listener started")
        launcher.run()
    except Exception:
        logging.exception("Voice listener stopped with an error")
        raise


if __name__ == "__main__":
    main()
