from __future__ import annotations

import inspect
import json
import threading
import time
from collections.abc import Callable

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static

from iris import __version__
from iris.application.content_policy import REFUSAL, ContentPolicy
from iris.config import Settings
from iris.tui.orb import BrailleOrb

TOOL_LABELS = {
    "web_search": "Pesquisando na web",
    "search_library": "Consultando a biblioteca",
    "learn_url": "Aprendendo",
    "read_file": "Lendo arquivo",
    "write_file": "Criando arquivo",
    "list_folder": "Olhando a pasta",
    "find_files": "Procurando arquivos",
    "create_folder": "Criando pasta",
    "move_files": "Movendo arquivos",
    "open_path": "Abrindo",
    "delete_files": "Lixeira",
    "run_command": "Comando",
    "open_app": "Abrindo programa",
    "close_app": "Fechando programa",
    "open_url": "Abrindo no navegador",
    "youtube": "YouTube",
    "get_weather": "Previsão do tempo",
    "remember": "Guardando na memória",
    "forget": "Esquecendo",
    "look_at_screen": "Olhando a tela",
    "click_on_screen": "Clicando na tela",
    "analyze_own_code": "Lendo o próprio código",
    "start_code_change": "Mudando o próprio código",
}
DETAIL_KEYS = ("query", "source", "path", "command", "name", "folder", "pattern", "url", "target", "content", "city")
SUGGESTIONS = (
    ("Qual a cotação do dólar hoje?", "pesquisa"),
    ("Cria um docker-compose com Postgres e Redis", "código"),
    ("O que tem na minha pasta de Downloads?", "arquivos"),
)
THINKING = "◐◓◑◒"
HELP = """**Comandos**

- `/nova` começa uma conversa nova
- `/memoria` mostra o que ela sabe sobre você · `/lembrar fato` ensina um fato
- `/biblioteca` lista os sites e documentos aprendidos · `/aprender link, arquivo ou pasta`
- `/limpar` limpa a tela · `/sair` fecha

Setas para cima e para baixo trazem mensagens anteriores."""


def describe(call) -> str:
    label = TOOL_LABELS.get(call.name, call.name)
    detail = next((str(call.input[k]) for k in DETAIL_KEYS if call.input.get(k)), "")
    detail = " ".join(detail.split())
    return f"{label} · {detail[:90]}" if detail else label


class ApprovalScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "deny", "Negar"), Binding("s", "allow", "Sim", show=False), Binding("n", "deny", "Não", show=False)]

    def __init__(self, call):
        super().__init__()
        self.call = call

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            yield Static("A Iris quer fazer uma ação", id="approval-title")
            yield Static(f"{describe(self.call)}\n\n{json.dumps(self.call.input, ensure_ascii=False, indent=2)[:900]}", id="approval-detail")
            with Horizontal(id="approval-buttons"):
                yield Button("Não", id="deny")
                yield Button("Permitir", id="allow", variant="warning")

    @on(Button.Pressed, "#allow")
    def action_allow(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#deny")
    def action_deny(self) -> None:
        self.dismiss(False)


class TuiApprover:
    def __init__(self, app: IrisApp):
        self.app = app

    def approve(self, call) -> bool:
        done = threading.Event()
        answer = {"value": False}

        def finish(value: bool | None) -> None:
            answer["value"] = bool(value)
            done.set()

        self.app.call_from_thread(self.app.push_screen, ApprovalScreen(call), finish)
        done.wait()
        return answer["value"]


class TuiSession:
    def __init__(self, app: IrisApp):
        self.app = app
        self.turn = 0

    def notify(self, text: str) -> None:
        self.app.call_from_thread(self.app.add_iris_text, text)

    def request_restart(self) -> None:
        self.app.call_from_thread(self.app.add_notice, "Mudança aplicada. Abra a Iris de novo para usar a versão nova.")

    def request_exit(self, mode: str) -> None:
        self.app.call_from_thread(self.app.exit)


class ToolLine(Static):
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, call):
        super().__init__(classes="tool")
        self.text = describe(call)
        self.frame = 0
        self.timer = None

    def on_mount(self) -> None:
        self.update(f"{self.FRAMES[0]} {self.text}")
        self.timer = self.set_interval(0.08, self.spin)

    def spin(self) -> None:
        self.frame = (self.frame + 1) % len(self.FRAMES)
        self.update(f"{self.FRAMES[self.frame]} {self.text}")

    def finish(self, ok: bool) -> None:
        if self.timer:
            self.timer.stop()
        self.update(f"{'✓' if ok else '✗'} {self.text}")
        self.add_class("done" if ok else "failed")


class HistoryInput(Input):
    BINDINGS = [Binding("up", "older", show=False), Binding("down", "newer", show=False)]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.position = 0

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.position = len(self.history)

    def action_older(self) -> None:
        if self.history and self.position > 0:
            self.position -= 1
            self.value = self.history[self.position]
            self.cursor_position = len(self.value)

    def action_newer(self) -> None:
        if self.position < len(self.history) - 1:
            self.position += 1
            self.value = self.history[self.position]
        else:
            self.position = len(self.history)
            self.value = ""
        self.cursor_position = len(self.value)


class IrisApp(App):
    CSS_PATH = "iris.tcss"
    TITLE = "Iris"
    BINDINGS = [
        Binding("ctrl+n", "new_chat", "Nova conversa"),
        Binding("ctrl+l", "clear", "Limpar"),
        Binding("ctrl+c", "quit", "Sair", priority=True),
    ]

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.policy = ContentPolicy()
        self.engine = None
        self.session = TuiSession(self)
        self.busy = False
        self.current: Markdown | None = None
        self.buffer = ""
        self.last_render = 0.0
        self.tools: dict[str, ToolLine] = {}
        self.awaiting_confirmation = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("◉ IRIS", id="brand")
            yield Static("", id="spacer")
            yield Static("carregando…", id="model")
        with VerticalScroll(id="log"):
            with Vertical(id="welcome"):
                with Center():
                    yield BrailleOrb(columns=40, rows=14, density=520, id="orb")
                name = f", {self.settings.user_name}" if self.settings.user_name else ""
                yield Static(f"Oi{name}.", id="hello")
                yield Static("Pergunte, peça uma pesquisa ou uma tarefa no seu PC.", id="tagline")
                with Center():
                    with Horizontal(id="suggestions"):
                        for index, (text, kind) in enumerate(SUGGESTIONS):
                            yield Button(f"{kind}\n{text}", id=f"suggestion-{index}", classes="suggestion")
        with Vertical(id="bottom"):
            yield Static("", id="thinking")
            with Horizontal(id="replies"):
                yield Button("Sim, pode", id="yes")
                yield Button("Não", id="no")
            yield HistoryInput(placeholder="Fale com a Iris…", id="prompt")
            with Horizontal(id="status"):
                yield Static("enter envia  ·  ↑ histórico  ·  /ajuda comandos", id="hints")
                yield Static("ctrl+n nova  ·  ctrl+l limpar  ·  ctrl+c sair", id="keys")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.thinking_frame = 0
        self.set_interval(0.12, self.animate_thinking)
        self.load_engine()

    def animate_thinking(self) -> None:
        if not self.busy:
            return
        self.thinking_frame = (self.thinking_frame + 1) % len(THINKING)
        self.query_one("#thinking", Static).update(f"{THINKING[self.thinking_frame]} pensando…")

    @on(Button.Pressed, ".suggestion")
    def suggestion(self, event: Button.Pressed) -> None:
        index = int(event.button.id.rsplit("-", 1)[1])
        self.send(SUGGESTIONS[index][0])

    @work(thread=True, exclusive=True, group="engine")
    def load_engine(self) -> None:
        from iris.composition import CLI, build_engine, uses_api

        try:
            engine = build_engine(self.settings, TuiApprover(self), self.session, CLI)
        except Exception as exc:
            self.call_from_thread(self.add_notice, f"Não consegui iniciar: {exc}")
            self.call_from_thread(self.query_one("#model", Static).update, "sem modelo")
            return
        backend = self.settings.llm_backend
        if backend == "local":
            label = f"{self.settings.local_model} · local"
        elif backend == "claude_code" or not uses_api(backend):
            label = "Claude Code"
        else:
            label = f"Claude · {self.settings.api_model}"
        self.engine = engine
        self.call_from_thread(self.query_one("#model", Static).update, f"● {label}")

    def log_widget(self) -> VerticalScroll:
        return self.query_one("#log", VerticalScroll)

    def mount_message(self, widget) -> None:
        log = self.log_widget()
        log.mount(widget)
        self.call_after_refresh(log.scroll_end, animate=False)

    def add_notice(self, text: str) -> None:
        self.mount_message(Static(text, classes="notice"))

    def add_iris_text(self, text: str) -> None:
        self.mount_message(Vertical(Static("◆ iris", classes="iris-label"), Markdown(text), classes="iris"))

    def add_user_text(self, text: str) -> None:
        self.mount_message(Horizontal(Static(text, classes="bubble"), classes="user-row"))

    def start_iris_message(self) -> None:
        self.buffer = ""
        self.current = Markdown("")
        self.mount_message(Vertical(Static("◆ iris", classes="iris-label"), self.current, classes="iris"))

    def stream(self, delta: str) -> None:
        self.buffer += delta
        now = time.monotonic()
        if now - self.last_render > 0.05:
            self.last_render = now
            self.call_from_thread(self.render_buffer)

    def render_buffer(self) -> None:
        if self.current is not None:
            self.current.update(self.buffer)
            self.call_after_refresh(self.log_widget().scroll_end, animate=False)

    def tool_event(self, event: str, call, result) -> None:
        if event == "start":
            self.call_from_thread(self.show_tool, call)
        else:
            self.call_from_thread(self.end_tool, call, result)

    def show_tool(self, call) -> None:
        if self.current is not None and not self.buffer.strip():
            self.current.parent.remove()
            self.current = None
        line = ToolLine(call)
        self.tools[call.id] = line
        self.mount_message(line)

    def end_tool(self, call, result) -> None:
        line = self.tools.pop(call.id, None)
        if line:
            line.finish(not result.is_error)
        if "Confirmation code" in result.content:
            self.awaiting_confirmation = True
        if self.current is None or self.buffer.strip():
            self.start_iris_message()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#thinking").set_class(busy, "visible")
        for orb in self.query(BrailleOrb):
            orb.energy = 1.0 if busy else 0.0
        self.query_one("#replies").set_class(not busy and self.awaiting_confirmation, "visible")

    @on(Input.Submitted, "#prompt")
    def submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        prompt = self.query_one("#prompt", HistoryInput)
        prompt.value = ""
        if not text:
            return
        prompt.remember(text)
        if text.startswith("/"):
            self.command(text)
            return
        self.send(text)

    @on(Button.Pressed, "#yes")
    def confirm_yes(self) -> None:
        self.send("sim, pode")

    @on(Button.Pressed, "#no")
    def confirm_no(self) -> None:
        self.send("não")

    def send(self, text: str) -> None:
        if self.busy:
            self.add_notice("Espere ela terminar a resposta atual.")
            return
        if self.engine is None:
            self.add_notice("Ainda carregando, tente de novo em um instante.")
            return
        self.awaiting_confirmation = False
        for welcome in self.query("#welcome"):
            welcome.remove()
        self.add_user_text(text)
        if self.policy.check(text):
            self.add_iris_text(REFUSAL)
            return
        self.start_iris_message()
        self.set_busy(True)
        self.ask(text)

    @work(thread=True, exclusive=True, group="ask")
    def ask(self, text: str) -> None:
        self.session.turn += 1
        kwargs: dict[str, Callable] = {"on_text": self.stream}
        if "on_tool" in inspect.signature(self.engine.ask).parameters:
            kwargs["on_tool"] = self.tool_event
        try:
            answer = self.engine.ask(text, **kwargs)
            if not self.buffer.strip() and answer:
                self.buffer = answer
        except Exception as exc:
            self.buffer += f"\n\nNão consegui responder: {exc}"
        self.call_from_thread(self.render_buffer)
        self.call_from_thread(self.set_busy, False)

    def command(self, text: str) -> None:
        name, _, arg = text.partition(" ")
        arg = arg.strip()
        if name in ("/sair", "/exit", "/quit"):
            self.exit()
        elif name == "/nova":
            self.action_new_chat()
        elif name == "/limpar":
            self.action_clear()
        elif name == "/ajuda":
            self.add_iris_text(HELP)
        elif name == "/memoria":
            self.show_memory()
        elif name == "/lembrar" and arg:
            from iris.knowledge.sqlite_memory import SQLiteMemory

            fact = SQLiteMemory(self.settings.memory_file).remember(arg)
            self.add_notice(f"Guardado como #{fact.id}.")
        elif name == "/biblioteca":
            self.show_library()
        elif name == "/aprender" and arg:
            self.learn(arg)
        else:
            self.add_notice("Comando desconhecido. /ajuda mostra os comandos.")

    def show_memory(self) -> None:
        from iris.knowledge.sqlite_memory import SQLiteMemory

        facts = SQLiteMemory(self.settings.memory_file).all()
        body = "\n".join(f"- `#{f.id}` {f.content}" for f in facts) or "Ela ainda não sabe nada sobre você. Ensine com `/lembrar fato`."
        self.add_iris_text(f"**O que eu sei sobre você**\n\n{body}")

    @work(thread=True, group="library")
    def show_library(self) -> None:
        from iris.composition import library_for

        sources = library_for(self.settings, index_in_background=False).sources()
        body = "\n".join(f"- **{title}** · {count} trechos  \n  {source}" for title, source, count in sources)
        self.call_from_thread(self.add_iris_text, f"**Biblioteca**\n\n{body or 'Vazia. Ensine com `/aprender link, arquivo ou pasta`.'}")

    @work(thread=True, group="library")
    def learn(self, source: str) -> None:
        from iris.composition import library_for

        self.call_from_thread(self.add_notice, f"Aprendendo {source}…")
        result = library_for(self.settings, index_in_background=False).learn(source)
        self.call_from_thread(self.add_notice, result)

    def action_new_chat(self) -> None:
        if self.engine is not None and hasattr(self.engine, "reset"):
            self.engine.reset()
        self.action_clear()
        self.add_notice("Conversa nova.")

    def action_clear(self) -> None:
        log = self.log_widget()
        for child in list(log.children):
            if child.id != "welcome":
                child.remove()
        log.scroll_home(animate=False)
        self.awaiting_confirmation = False
        self.set_busy(self.busy)


def run(settings: Settings) -> None:
    IrisApp(settings).run()
