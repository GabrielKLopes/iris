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
from rich.text import Text
from textual.widgets import Button, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

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
    "Qual a cotação do dólar hoje?",
    "Me ajuda a montar um orçamento do mês",
    "O que tem na minha pasta de Downloads?",
    "Explica como funciona o imposto de renda",
)
SIDE_MIN_WIDTH = 96
STATES = {
    "idle": ("esperando", 0.0),
    "thinking": ("pensando…", 0.6),
    "answering": ("respondendo", 1.0),
    "tool": ("trabalhando", 0.8),
}
COMMANDS = (
    ("help", "mostra os comandos", False),
    ("new", "começa uma conversa nova", False),
    ("clear", "limpa a tela", False),
    ("memory", "mostra o que ela sabe sobre você", False),
    ("remember", "ensina um fato, ex.: /remember moro em Recife", True),
    ("forget", "apaga um fato pelo número, ex.: /forget 6", True),
    ("library", "lista os sites e documentos aprendidos", False),
    ("learn", "aprende um link, arquivo ou pasta", True),
    ("model", "mostra qual modelo está respondendo", False),
    ("exit", "fecha a Iris", False),
)
NEEDS_ARGUMENT = {name for name, _, takes in COMMANDS if takes}
HELP = "**Comandos**\n\n" + "\n".join(f"- `/{name}` {description}" for name, description, _ in COMMANDS) + (
    "\n\nDigite `/` para ver a lista. Setas para cima e para baixo trazem mensagens anteriores."
)


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
        self.update(f"⎿ {self.FRAMES[0]} {self.text}")
        self.timer = self.set_interval(0.08, self.spin)

    def spin(self) -> None:
        self.frame = (self.frame + 1) % len(self.FRAMES)
        self.update(f"⎿ {self.FRAMES[self.frame]} {self.text}")

    def finish(self, ok: bool) -> None:
        if self.timer:
            self.timer.stop()
        self.update(f"⎿ {'✓' if ok else '✗'} {self.text}")
        self.add_class("done" if ok else "failed")


class HistoryInput(Input):
    BINDINGS = [
        Binding("up", "older", show=False),
        Binding("down", "newer", show=False),
        Binding("tab", "complete", show=False, priority=True),
        Binding("escape", "close_menu", show=False),
    ]

    def action_complete(self) -> None:
        if self.app.menu_visible():
            self.app.complete_command()

    def action_close_menu(self) -> None:
        self.app.hide_menu()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.position = 0

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.position = len(self.history)

    def action_older(self) -> None:
        if self.app.menu_visible():
            self.app.menu_move(-1)
            return
        if self.history and self.position > 0:
            self.position -= 1
            self.value = self.history[self.position]
            self.cursor_position = len(self.value)

    def action_newer(self) -> None:
        if self.app.menu_visible():
            self.app.menu_move(1)
            return
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
        self.state = "idle"

    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="side"):
                with Center():
                    yield BrailleOrb(columns=24, rows=10, density=420, id="orb")
                yield Static("esperando", id="state")
                yield Static("", id="side-rule")
                yield Static("carregando…", id="model")
                yield Static(self.settings.user_name or "", id="who")
                yield Static("", id="facts")
                yield Static(f"iris {__version__}", id="version")
            with Vertical(id="main"):
                with VerticalScroll(id="log"):
                    with Vertical(id="welcome"):
                        name = f", {self.settings.user_name}" if self.settings.user_name else ""
                        yield Static(f"Oi{name}.", id="hello")
                        yield Static("O que você quer fazer agora?", id="tagline")
                        for index, text in enumerate(SUGGESTIONS):
                            yield Button(f"› {text}", id=f"suggestion-{index}", classes="suggestion")
                with Vertical(id="bottom"):
                    yield OptionList(id="commands")
                    with Horizontal(id="replies"):
                        yield Button("Sim, pode", id="yes")
                        yield Button("Não", id="no")
                    yield HistoryInput(placeholder="Fale com a Iris…", id="prompt")
                    with Horizontal(id="status"):
                        yield Static("enter envia  ·  ↑ histórico  ·  / comandos", id="hints")
                        yield Static("ctrl+n nova  ·  ctrl+c sair", id="keys")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.fit_side(self.size.width)
        self.load_engine()
        self.load_counts()

    def on_resize(self, event) -> None:
        self.fit_side(event.size.width)

    def fit_side(self, width: int) -> None:
        self.query_one("#side").display = width >= SIDE_MIN_WIDTH

    def set_state(self, state: str, label: str | None = None) -> None:
        self.state = state
        text, energy = STATES[state]
        self.query_one("#state", Static).update(label or text)
        self.query_one("#state").set_class(state != "idle", "active")
        self.query_one("#orb", BrailleOrb).energy = energy

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
            label = f"{self.settings.local_model}\nlocal, no seu PC"
        elif backend == "claude_code" or not uses_api(backend):
            label = "Claude Code"
        else:
            label = f"Claude\n{self.settings.api_model}"
        self.engine = engine
        self.call_from_thread(self.query_one("#model", Static).update, label)

    @work(thread=True, group="counts")
    def load_counts(self) -> None:
        try:
            from iris.knowledge.sqlite_memory import SQLiteMemory

            facts = len(SQLiteMemory(self.settings.memory_file).all())
            import sqlite3

            library = 0
            if self.settings.library_db.exists():
                with sqlite3.connect(self.settings.library_db) as db:
                    library = db.execute("SELECT count(*) FROM sources").fetchone()[0]
            self.call_from_thread(self.query_one("#facts", Static).update, f"{facts} fatos sobre você\n{library} fontes na biblioteca")
        except Exception:
            pass

    def log_widget(self) -> VerticalScroll:
        return self.query_one("#log", VerticalScroll)

    def mount_message(self, widget) -> None:
        log = self.log_widget()
        log.mount(widget)
        self.call_after_refresh(log.scroll_end, animate=False)

    def add_notice(self, text: str) -> None:
        self.mount_message(Static(text, classes="notice"))

    def iris_block(self, markdown: Markdown) -> Horizontal:
        return Horizontal(Static("●", classes="dot"), markdown, classes="iris")

    def add_iris_text(self, text: str) -> None:
        self.mount_message(self.iris_block(Markdown(text)))

    def add_user_text(self, text: str) -> None:
        self.mount_message(Horizontal(Static("›", classes="caret"), Static(text, classes="said"), classes="user"))

    def start_iris_message(self) -> None:
        self.buffer = ""
        self.current = Markdown("")
        self.mount_message(self.iris_block(self.current))

    def stream(self, delta: str) -> None:
        if not self.buffer:
            self.call_from_thread(self.set_state, "answering")
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
        self.set_state("tool", TOOL_LABELS.get(call.name, "trabalhando").lower())
        line = ToolLine(call)
        self.tools[call.id] = line
        self.mount_message(line)

    def end_tool(self, call, result) -> None:
        line = self.tools.pop(call.id, None)
        if line:
            line.finish(not result.is_error)
        if "Confirmation code" in result.content:
            self.awaiting_confirmation = True
        self.set_state("thinking")
        if self.current is None or self.buffer.strip():
            self.start_iris_message()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.set_state("thinking" if busy else "idle")
        self.query_one("#replies").set_class(not busy and self.awaiting_confirmation, "visible")

    def menu(self) -> OptionList:
        return self.query_one("#commands", OptionList)

    def menu_visible(self) -> bool:
        return self.menu().has_class("visible")

    def hide_menu(self) -> None:
        self.menu().remove_class("visible")

    def menu_move(self, step: int) -> None:
        menu = self.menu()
        if menu.option_count:
            menu.highlighted = ((menu.highlighted or 0) + step) % menu.option_count

    @on(Input.Changed, "#prompt")
    def typing(self, event: Input.Changed) -> None:
        value = event.value
        if not value.startswith("/") or " " in value:
            self.hide_menu()
            return
        typed = value[1:].lower()
        matches = [(name, description) for name, description, _ in COMMANDS if name.startswith(typed)]
        menu = self.menu()
        menu.clear_options()
        if not matches:
            self.hide_menu()
            return
        for name, description in matches:
            label = Text.assemble((f"/{name:<10}", "bold #e9b04c"), (description, "#a0968a"))
            menu.add_option(Option(label, id=name))
        menu.highlighted = 0
        menu.add_class("visible")

    def complete_command(self, run: bool = False) -> None:
        menu = self.menu()
        if menu.highlighted is None:
            return
        name = menu.get_option_at_index(menu.highlighted).id
        prompt = self.query_one("#prompt", HistoryInput)
        self.hide_menu()
        if name in NEEDS_ARGUMENT or not run:
            prompt.value = f"/{name} " if name in NEEDS_ARGUMENT else f"/{name}"
            prompt.cursor_position = len(prompt.value)
            prompt.focus()
            return
        prompt.value = ""
        prompt.remember(f"/{name}")
        self.command(f"/{name}")

    @on(OptionList.OptionSelected, "#commands")
    def command_clicked(self, event: OptionList.OptionSelected) -> None:
        self.complete_command(run=True)

    @on(Input.Submitted, "#prompt")
    def submitted(self, event: Input.Submitted) -> None:
        if self.menu_visible():
            self.complete_command(run=True)
            return
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

    @on(Button.Pressed, ".suggestion")
    def suggestion(self, event: Button.Pressed) -> None:
        self.send(SUGGESTIONS[int(event.button.id.rsplit("-", 1)[1])])

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
        self.call_from_thread(self.load_counts)

    def command(self, text: str) -> None:
        name, _, arg = text.partition(" ")
        name = name.lstrip("/").lower()
        arg = arg.strip()
        if name in ("exit", "quit"):
            self.exit()
        elif name == "new":
            self.action_new_chat()
        elif name == "clear":
            self.action_clear()
        elif name == "help":
            self.add_iris_text(HELP)
        elif name == "memory":
            self.show_memory()
        elif name == "remember" and arg:
            from iris.knowledge.sqlite_memory import SQLiteMemory

            fact = SQLiteMemory(self.settings.memory_file).remember(arg)
            self.add_notice(f"Guardado como #{fact.id}.")
            self.load_counts()
        elif name == "forget" and arg.lstrip("#").isdigit():
            from iris.knowledge.sqlite_memory import SQLiteMemory

            forgotten = SQLiteMemory(self.settings.memory_file).forget(int(arg.lstrip("#")))
            self.add_notice("Esquecido." if forgotten else "Não encontrei esse fato. Veja os números com /memory.")
            self.load_counts()
        elif name == "library":
            self.show_library()
        elif name == "learn" and arg:
            self.learn(arg)
        elif name == "model":
            self.add_notice(f"Respondendo com {str(self.query_one('#model', Static).render()).replace(chr(10), ' · ')}.")
        elif name in NEEDS_ARGUMENT:
            self.add_notice(f"Faltou o complemento. Exemplo: {dict((n, d) for n, d, _ in COMMANDS)[name].split('ex.: ')[-1]}")
        else:
            self.add_notice("Comando desconhecido. Digite / para ver a lista.")

    def show_memory(self) -> None:
        from iris.knowledge.sqlite_memory import SQLiteMemory

        facts = SQLiteMemory(self.settings.memory_file).all()
        body = "\n".join(f"- `#{f.id}` {f.content}" for f in facts) or "Ela ainda não sabe nada sobre você. Ensine com `/remember fato`."
        self.add_iris_text(f"**O que eu sei sobre você**\n\n{body}")

    @work(thread=True, group="library")
    def show_library(self) -> None:
        from iris.composition import library_for

        sources = library_for(self.settings, index_in_background=False).sources()
        body = "\n".join(f"- **{title}** · {count} trechos  \n  {source}" for title, source, count in sources)
        self.call_from_thread(self.add_iris_text, f"**Biblioteca**\n\n{body or 'Vazia. Ensine com `/learn link, arquivo ou pasta`.'}")

    @work(thread=True, group="library")
    def learn(self, source: str) -> None:
        from iris.composition import library_for

        self.call_from_thread(self.add_notice, f"Aprendendo {source}…")
        result = library_for(self.settings, index_in_background=False).learn(source)
        self.call_from_thread(self.add_notice, result)
        self.call_from_thread(self.load_counts)

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
        self.awaiting_confirmation = False
        self.query_one("#replies").set_class(False, "visible")
        log.scroll_home(animate=False)


def run(settings: Settings) -> None:
    from iris.tui import terminal_profile

    try:
        terminal_profile.install()
    except OSError:
        pass
    terminal_profile.set_title()
    IrisApp(settings).run()
