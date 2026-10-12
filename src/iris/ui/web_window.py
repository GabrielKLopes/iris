import json
import logging
from pathlib import Path
import queue
import re
import threading
import time
from collections.abc import Callable
from importlib import resources

import webview

from iris import __version__
from iris.application.content_policy import REFUSAL, ContentPolicy
from iris.application.intent import ASSISTANT_NAMES, is_echo, is_hold, normalize
from iris.domain.models import ToolCall
from iris.infrastructure.voice.neural_speaker import clean_for_speech

log = logging.getLogger(__name__)

def with_screen_context(question: str) -> str:
    try:
        from iris.infrastructure.windows.keyboard import active_window_title

        title = active_window_title()
    except Exception:
        title = ""
    return f"{question}\n\n<screen>Janela ativa: {title}</screen>" if title else question


IGNORE_MARK = "[ignorar]"
SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")

WAKE_FILLERS = {"oi", "ei", "ok", "fala", "bom", "boa", "dia", "tarde", "noite", "e", "a", "o"} | ASSISTANT_NAMES


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Bom dia"
    if 12 <= hour < 18:
        return "Boa tarde"
    return "Boa noite"


def wake_reply(spotted: str, user_name: str, hour: int) -> str:
    clean = normalize(spotted)
    for salutation in ("bom dia", "boa tarde", "boa noite"):
        if salutation in clean:
            return f"{salutation.capitalize()}, {user_name}! Em que posso ajudar?"
    return f"Oi, {user_name}. Pode falar."


def split_wake(spotted: str, full: str) -> tuple[bool, str]:
    if not set(normalize(spotted).split()) & ASSISTANT_NAMES:
        return False, ""
    words = normalize(full).split()
    while words and words[0] in WAKE_FILLERS:
        words.pop(0)
    question = " ".join(words)
    return True, question if len(words) >= 2 else ""


class WebApprover:
    def __init__(self):
        self.window: webview.Window | None = None

    def approve(self, call: ToolCall) -> bool:
        if self.window is None:
            return False
        return bool(self.window.create_confirmation_dialog("Iris pede aprovação", f"Executar {call.name}?\n\n{call.input}"))


class IrisApi:
    def __init__(self):
        self._window: webview.Window | None = None
        self._on_ask: Callable[[str], str] | None = None
        self._on_reset: Callable[[], None] | None = None
        self._on_speak: Callable[[str], None] | None = None
        self._on_speak_stream = None
        self._on_interrupt = None
        self._corrector = None
        self._router = None
        self._policy = ContentPolicy()
        self._on_duck = None
        self.turn = 0
        self.hidden = False
        self._restart_pending = False
        self._exit_pending = ""
        self._interrupt_requested = threading.Event()
        self._recognizer = None
        self._notice: str | None = None
        self._listen_on_boot = False
        self._maximized = False
        self._active = threading.Event()
        self._wake_stop = threading.Event()
        self._last_level_push = 0.0
        self._pushes: queue.Queue = queue.Queue(maxsize=256)
        self._pusher: threading.Thread | None = None
        self._user_name = ""

    def configure(
        self,
        on_ask=None,
        on_reset=None,
        on_speak=None,
        recognizer=None,
        notice=None,
        listen_on_boot=False,
        user_name="",
        on_speak_stream=None,
        on_interrupt=None,
        on_duck=None,
        corrector=None,
        router=None,
    ) -> None:
        self._corrector = corrector
        self._router = router
        self._on_duck = on_duck
        self._on_speak_stream = on_speak_stream
        self._on_interrupt = on_interrupt
        self._user_name = user_name
        self._on_ask = on_ask
        self._on_reset = on_reset
        self._on_speak = on_speak
        self._recognizer = recognizer
        self._notice = notice
        self._listen_on_boot = listen_on_boot

    def attach(self, window: webview.Window) -> None:
        self._window = window

    def _push(self, function: str, value) -> None:
        if self._window is None:
            return
        if self._pusher is None:
            self._pusher = threading.Thread(target=self._drain_pushes, daemon=True)
            self._pusher.start()
        try:
            self._pushes.put_nowait((function, value))
        except queue.Full:
            pass

    def _drain_pushes(self) -> None:
        while True:
            function, value = self._pushes.get()
            if function == "level" and not self._pushes.empty():
                continue
            try:
                self._window.evaluate_js(f"window.iris && window.iris.{function}({json.dumps(value)})")
            except Exception:
                pass

    def _push_level(self, level: float) -> None:
        now = time.monotonic()
        if now - self._last_level_push >= 0.05:
            self._last_level_push = now
            self._push("level", round(level, 3))

    def boot(self) -> dict:
        if self._recognizer is not None:
            threading.Thread(target=self._wake_loop, daemon=True).start()
        return {
            "listen": self._listen_on_boot and self._recognizer is not None,
            "voice": self._recognizer is not None,
            "notice": self._notice,
            "version": __version__,
            "greeting": f"{greeting(time.localtime().tm_hour)}, {self._user_name}! Estou aqui. Em que posso ajudar?",
            "hidden": self.hidden,
        }

    def _wake_loop(self) -> None:
        log.info("Wake loop started")
        while not self._wake_stop.is_set():
            if self._active.is_set():
                time.sleep(0.2)
                continue
            try:
                for heard_phrase in self._recognizer.phrases(stop=self._active, on_level=self._push_level):
                    phrase = self._fix(heard_phrase)
                    woke, question = split_wake(phrase, phrase)
                    if woke:
                        if not question:
                            question = self._recognizer.listen_once(on_level=self._push_level, silence_timeout=1.5)
                        log.info("Wake phrase %r question=%r", phrase, question)
                        reply = "" if question else wake_reply(phrase, self._user_name, time.localtime().tm_hour)
                        self.show()
                        self._push("wake", {"question": question, "reply": reply})
                        time.sleep(1.0)
                        break
            except Exception:
                log.exception("Wake loop failed")
                time.sleep(2)

    def ask(self, question: str) -> dict:
        if self._on_ask is None:
            return {"answer": self._notice or "Não estou conectada a um modelo.", "error": True}
        try:
            return {"answer": self._on_ask(question), "error": False}
        except Exception as exc:
            return {"answer": f"Tive um problema: {exc}", "error": True}

    def _quick_answer(self, text: str, speak: bool) -> dict:
        if speak and self._on_speak_stream:
            self._active.set()
            try:
                self._on_speak_stream(iter([text]), on_level=self._push_level, on_start=lambda: self._push("phase", "speaking"))
            finally:
                self._active.clear()
        if self._exit_pending:
            action = self.quit if self._exit_pending == "quit" else self.close
            self._exit_pending = ""
            threading.Timer(0.3, action).start()
        return {"answer": text, "error": False}

    def _fix(self, text: str) -> str:
        if not text or self._corrector is None:
            return text
        try:
            fixed, corrections = self._corrector.correct(text)
        except Exception:
            log.exception("Transcript correction failed")
            return text
        for correction in corrections:
            log.info("Corrected %r -> %r (%.2f)", correction.heard, correction.replaced_by, correction.score)
        return fixed

    def converse(self, question: str, speak: bool = True) -> dict:
        if self._on_ask is None:
            return {"answer": self._notice or "Não estou conectada a um modelo.", "error": True}
        self.turn += 1
        violation = self._policy.check(question)
        if violation:
            log.info("Refused by content policy (%s): %r", violation.category, violation.match)
            return self._quick_answer(REFUSAL, speak)
        if self._router is not None:
            route = self._router.route(question)
            if route.kind == "refuse":
                return self._quick_answer(REFUSAL, speak)
            if route.kind == "ignore":
                log.info("Router ignored: %r", question)
                return {"answer": "", "error": False, "ignored": True}
            if route.kind == "done":
                return self._quick_answer(route.reply, speak)
        sentences: queue.Queue[str | None] = queue.Queue()
        pending: list[str] = []
        streamed: list[str] = []

        def on_text(delta: str) -> None:
            streamed.append(delta)
            if "".join(streamed).lstrip().startswith("[") or self._policy.check("".join(streamed)):
                return
            self._push("caption", clean_for_speech("".join(streamed)))
            parts = SENTENCE_BREAK.split("".join(pending) + delta)
            for sentence in parts[:-1]:
                if sentence.strip() and not self._policy.check(sentence):
                    sentences.put(sentence.strip())
            pending[:] = [parts[-1]]

        def sentence_stream():
            while (sentence := sentences.get()) is not None:
                yield sentence

        self._interrupt_requested.clear()
        barge: dict[str, str] = {}
        settled = threading.Event()

        def duck(volume: float) -> None:
            if self._on_duck:
                self._on_duck(volume)

        def heard_something() -> None:
            barge["hearing"] = "1"
            duck(0.25)

        def watch_for_barge_in() -> None:
            try:
                for utterance in self._recognizer.utterances(
                    stop=settled, on_level=self._push_level, on_onset=heard_something, sensitivity=2.0
                ):
                    heard = self._fix(self._recognizer.transcriber.transcribe(utterance))
                    barge.pop("hearing", None)
                    if is_echo(heard, "".join(streamed)):
                        log.info("Ignored own voice or noise: %r", heard)
                        duck(1.0)
                        if barge.get("done"):
                            return
                        continue
                    log.info("Barge-in: %r", heard)
                    barge["onset"] = "1"
                    if self._on_interrupt:
                        self._on_interrupt()
                    self._push("phase", "listening")
                    barge["text"] = "" if is_hold(heard) else heard
                    return
            except Exception:
                log.exception("Barge-in watcher failed")

        voice = None
        watcher = None
        if speak and self._on_speak_stream:
            self._active.set()
            voice = threading.Thread(
                target=self._on_speak_stream,
                args=(sentence_stream(),),
                kwargs={"on_level": self._push_level, "on_start": lambda: self._push("phase", "speaking")},
                daemon=True,
            )
            voice.start()
            if self._recognizer is not None:
                watcher = threading.Thread(target=watch_for_barge_in, daemon=True)
                watcher.start()
        try:
            answer, error = self._on_ask(with_screen_context(question), on_text=on_text), False
        except Exception as exc:
            log.exception("Ask failed")
            answer, error = f"Tive um problema: {exc}", True
        ignored = answer.strip().startswith(IGNORE_MARK)
        rest = "".join(pending).strip()
        if rest and not error and not ignored and not self._policy.check(rest):
            sentences.put(rest)
        sentences.put(None)
        if voice:
            while voice.is_alive():
                if self._interrupt_requested.is_set() and self._on_interrupt:
                    self._on_interrupt()
                voice.join(0.1)
            barge["done"] = "1"
            if watcher and (barge.get("onset") or barge.get("hearing")):
                watcher.join(20)
            settled.set()
            self._active.clear()
        if self._restart_pending:
            threading.Timer(0.5, self._restart_now).start()
        elif self._exit_pending:
            action = self.quit if self._exit_pending == "quit" else self.close
            self._exit_pending = ""
            threading.Timer(0.3, action).start()
        if ignored:
            log.info("Ignored as not addressed to Iris: %r", question)
            return {"answer": "", "error": False, "ignored": True}
        if self._policy.check(answer):
            log.info("Answer blocked by content policy")
            answer = REFUSAL
        return {
            "answer": clean_for_speech(answer),
            "error": error,
            "interruptedBy": barge.get("text", ""),
            "interrupted": bool(barge.get("onset")) or self._interrupt_requested.is_set(),
        }

    def interrupt(self) -> None:
        self._interrupt_requested.set()
        if self._on_interrupt:
            self._on_interrupt()

    def move_to_screen(self, number: int) -> str:
        screens = webview.screens
        if not 1 <= number <= len(screens):
            return f"There are {len(screens)} monitors; monitor {number} does not exist"
        if self._window is None:
            return "Window not ready"
        screen = screens[number - 1]
        x = screen.x + (screen.width - self._window.width) // 2
        y = screen.y + (screen.height - self._window.height) // 2
        self._window.move(x, y)
        return f"Moved to monitor {number}"

    def next_screen(self) -> None:
        screens = webview.screens
        if not screens or self._window is None:
            return
        center_x = self._window.x + self._window.width // 2
        current = next(
            (i for i, s in enumerate(screens) if s.x <= center_x < s.x + s.width),
            0,
        )
        self.move_to_screen((current + 1) % len(screens) + 1)

    def say(self, text: str) -> None:
        if self._on_speak and text:
            self._active.set()
            try:
                self._on_speak(text, on_level=self._push_level)
            finally:
                self._active.clear()

    def listen(self, timeout: float = 10.0) -> str:
        if self._recognizer is None:
            raise RuntimeError("Microfone indisponível")
        self._active.set()
        try:
            while True:
                text = self._fix(self._recognizer.listen_once(on_level=self._push_level, silence_timeout=timeout))
                log.info("Listened: %r", text)
                if not is_hold(text):
                    return text
        finally:
            self._push("level", 0)
            self._active.clear()

    def reset(self) -> None:
        if self._on_reset:
            self._on_reset()

    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def toggle_maximize(self) -> None:
        if not self._window:
            return
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized

    def close(self) -> None:
        if self._window:
            self._window.hide()
            self.hidden = True

    def show(self) -> None:
        if self._window and self.hidden:
            self._window.show()
            self._window.restore()
            self.hidden = False

    def notify(self, text: str) -> None:
        self.show()
        self._push("notify", text)

    def request_exit(self, mode: str) -> None:
        self._exit_pending = mode

    def request_restart(self) -> None:
        self._restart_pending = True

    def _restart_now(self) -> None:
        import subprocess
        import sys

        pythonw = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen(
            f'cmd /c timeout /t 3 /nobreak >nul & start "" "{pythonw}" -m iris',
            cwd=str(Path(__file__).resolve().parents[3]),
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        self.quit()

    def quit(self) -> None:
        self._wake_stop.set()
        self._active.set()
        if self._window:
            self._window.destroy()


def index_path() -> str:
    return str(resources.files("iris.ui").joinpath("web/index.html"))


def open_window(api: IrisApi, approver: WebApprover, hidden: bool = False) -> None:
    api.hidden = hidden
    window = webview.create_window(
        "Iris",
        url=index_path(),
        js_api=api,
        width=400,
        height=400,
        resizable=False,
        frameless=True,
        easy_drag=False,
        transparent=True,
        shadow=False,
        on_top=True,
        hidden=hidden,
    )
    api.attach(window)
    approver.window = window
    webview.start(gui="qt", icon=str(resources.files("iris.ui").joinpath("assets/iris.png")))
