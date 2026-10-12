import logging
import socket
import sys
import threading

from iris.composition import DESKTOP, build_engine, corrector_for, router_for
from iris.config import Settings
from iris.knowledge.sqlite_memory import SQLiteMemory
from iris.ui.web_window import IrisApi, WebApprover, open_window

SINGLE_INSTANCE_PORT = 47615


def _already_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=1) as connection:
            connection.sendall(b"show")
        return True
    except OSError:
        return False


def _serve_show_requests(api: IrisApi) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    server.listen()

    def loop():
        while True:
            connection, _ = server.accept()
            with connection:
                if connection.recv(16) == b"show":
                    api.show()

    threading.Thread(target=loop, daemon=True).start()


def _voice(settings: Settings, notices: list[str]):
    try:
        from iris.infrastructure.voice.neural_speaker import NeuralSpeaker
        from iris.infrastructure.voice.speaker import WindowsSpeaker
        from iris.infrastructure.voice.speech_capture import SpeechCapture
        from iris.infrastructure.voice.whisper_transcriber import WhisperTranscriber

        transcriber = WhisperTranscriber(settings.whisper_model, settings.data_dir / "models" / "whisper")
        transcriber.preload()
        hint_memory = SQLiteMemory(settings.memory_file)
        transcriber.extra_hint = lambda: " ".join(f.content for f in hint_memory.all()[-30:])
        recognizer = SpeechCapture(transcriber, device=settings.input_device)
        speaker = NeuralSpeaker(voice=settings.voice_name, fallback=WindowsSpeaker(), device=settings.output_device)
        return recognizer, speaker
    except Exception as exc:
        notices.append(f"Voz indisponível: {exc}")
        return None, None


def main():
    if _already_running():
        return
    settings = Settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=settings.log_dir / "iris.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    api = IrisApi()
    approver = WebApprover()
    notices: list[str] = []
    engine = None
    try:
        engine = build_engine(settings, approver, api, DESKTOP)
    except Exception as exc:
        notices.append(f"Não consegui conectar a um modelo: {exc}")
    logging.info("Engine ready")
    recognizer, speaker = _voice(settings, notices)
    logging.info("Voice ready")

    api.configure(
        on_ask=engine.ask if engine else None,
        on_reset=engine.reset if engine else None,
        on_speak=speaker.say if speaker else None,
        on_speak_stream=speaker.speak_stream if speaker else None,
        on_interrupt=speaker.interrupt if speaker else None,
        on_duck=speaker.duck if speaker else None,
        corrector=corrector_for(settings),
        router=router_for(api),
        recognizer=recognizer,
        notice=" ".join(notices) or None,
        listen_on_boot="--listen" in sys.argv,
        user_name=settings.user_name,
    )
    _serve_show_requests(api)
    open_window(api, approver, hidden="--hidden" in sys.argv)


if __name__ == "__main__":
    main()
