from __future__ import annotations

import inspect
import json
import threading
import time
from collections.abc import Callable

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from iris import __version__
from iris.application.content_policy import REFUSAL, ContentPolicy
from iris.config import Settings
from iris.i18n import LANGUAGES, normalize, tr
from iris.tui.orb import BrailleOrb

DETAIL_KEYS = ("query", "source", "path", "command", "name", "folder", "pattern", "url", "target", "content", "city")
SUGGESTION_COUNT = 4
SIDE_MIN_WIDTH = 96
ENERGY = {"idle": 0.0, "thinking": 0.6, "answering": 1.0, "tool": 0.8}
COMMANDS = (
    ("help", False),
    ("new", False),
    ("clear", False),
    ("memory", False),
    ("remember", True),
    ("forget", True),
    ("library", False),
    ("learn", True),
    ("model", False),
    ("usage", False),
    ("language", True),
    ("key", False),
    ("exit", False),
)
NEEDS_ARGUMENT = {name for name, takes in COMMANDS if takes}
PERIOD_KEYS = {"today": "usage.period.today", "week": "usage.period.week", "month": "usage.period.month", "all": "usage.period.all"}


def describe(call, language: str) -> str:
    key = f"tool.{call.name}"
    label = tr(language, key)
    label = call.name if label == key else label
    detail = next((str(call.input[k]) for k in DETAIL_KEYS if call.input.get(k)), "")
    detail = " ".join(detail.split())
    return f"{label} · {detail[:90]}" if detail else label


class ApprovalScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "deny", show=False), Binding("y", "allow", show=False), Binding("n", "deny", show=False)]

    def __init__(self, call, language: str):
        super().__init__()
        self.call = call
        self.language = language

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            yield Static(tr(self.language, "approval.title"), id="approval-title")
            yield Static(f"{describe(self.call, self.language)}\n\n{json.dumps(self.call.input, ensure_ascii=False, indent=2)[:900]}", id="approval-detail")
            with Horizontal(id="approval-buttons"):
                yield Button(tr(self.language, "approval.deny"), id="deny")
                yield Button(tr(self.language, "approval.allow"), id="allow", variant="warning")

    @on(Button.Pressed, "#allow")
    def action_allow(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#deny")
    def action_deny(self) -> None:
        self.dismiss(False)


class KeyScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, provider: str, site: str, language: str):
        super().__init__()
        self.provider = provider
        self.site = site
        self.language = language

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            yield Static(tr(self.language, "key.prompt", provider=self.provider.title(), site=self.site), id="approval-title")
            yield Input(password=True, id="key-input")
            with Horizontal(id="approval-buttons"):
                yield Button(tr(self.language, "key.cancel"), id="cancel")
                yield Button(tr(self.language, "key.save"), id="save", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#key-input", Input).focus()

    @on(Input.Submitted, "#key-input")
    @on(Button.Pressed, "#save")
    def save(self) -> None:
        self.dismiss(self.query_one("#key-input", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss("")


class TuiApprover:
    def __init__(self, app: IrisApp):
        self.app = app

    def approve(self, call) -> bool:
        done = threading.Event()
        answer = {"value": False}

        def finish(value: bool | None) -> None:
            answer["value"] = bool(value)
            done.set()

        self.app.call_from_thread(self.app.push_screen, ApprovalScreen(call, self.app.language), finish)
        done.wait()
        return answer["value"]


class TuiSession:
    def __init__(self, app: IrisApp):
        self.app = app
        self.turn = 0

    def notify(self, text: str) -> None:
        self.app.call_from_thread(self.app.add_iris_text, text)

    def request_restart(self) -> None:
        self.app.call_from_thread(self.app.add_notice, self.app.t("restart"))

    def request_exit(self, mode: str) -> None:
        self.app.call_from_thread(self.app.exit)


class ToolLine(Static):
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, call, language: str):
        super().__init__(classes="tool")
        self.text = describe(call, language)
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.position = 0

    def action_complete(self) -> None:
        if self.app.menu_visible():
            self.app.complete_command()

    def action_close_menu(self) -> None:
        self.app.hide_menu()

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
        Binding("ctrl+n", "new_chat", show=False),
        Binding("ctrl+l", "clear", show=False),
        Binding("ctrl+c", "quit", show=False, priority=True),
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
        self.conversation_tokens = 0
        self.model_label = ""

    @property
    def language(self) -> str:
        return normalize(self.settings.language)

    def t(self, key: str, **values) -> str:
        return tr(self.language, key, **values)

    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="side"):
                with Center():
                    yield BrailleOrb(columns=24, rows=10, density=420, id="orb")
                yield Static(self.t("state.idle"), id="state")
                yield Static("", id="side-rule")
                yield Static(self.t("loading"), id="model")
                yield Static("", id="who")
                yield Static("", id="usage")
                yield Static("", id="facts")
                yield Static(f"iris {__version__}", id="version")
            with Vertical(id="main"):
                with VerticalScroll(id="log"):
                    with Vertical(id="welcome"):
                        yield Static("", id="hello")
                        yield Static("", id="tagline")
                        for index in range(SUGGESTION_COUNT):
                            yield Button("", id=f"suggestion-{index}", classes="suggestion")
                with Vertical(id="bottom"):
                    yield OptionList(id="commands")
                    with Horizontal(id="replies"):
                        yield Button("", id="yes")
                        yield Button("", id="no")
                    yield HistoryInput(id="prompt")
                    with Horizontal(id="status"):
                        yield Static("", id="hints")
                        yield Static("", id="keys")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.fit_side(self.size.width)
        self.apply_language()
        self.load_engine()
        self.load_counts()
        self.show_usage()

    def apply_language(self) -> None:
        name = f", {self.settings.user_name}" if self.settings.user_name else ""
        for welcome in self.query("#welcome"):
            welcome.query_one("#hello", Static).update(self.t("hello", name=name))
            welcome.query_one("#tagline", Static).update(self.t("tagline"))
            for index in range(SUGGESTION_COUNT):
                welcome.query_one(f"#suggestion-{index}", Button).label = f"› {self.t(f'suggestion.{index}')}"
        self.query_one("#prompt", Input).placeholder = self.t("placeholder")
        self.query_one("#hints", Static).update(self.t("hints"))
        self.query_one("#keys", Static).update(self.t("keys"))
        self.query_one("#yes", Button).label = self.t("yes")
        self.query_one("#no", Button).label = self.t("no")
        self.set_state(self.state)

    def on_resize(self, event) -> None:
        self.fit_side(event.size.width)

    def fit_side(self, width: int) -> None:
        self.query_one("#side").display = width >= SIDE_MIN_WIDTH

    def set_state(self, state: str, label: str | None = None) -> None:
        self.state = state
        self.query_one("#state", Static).update(label or self.t(f"state.{state}"))
        self.query_one("#state").set_class(state != "idle", "active")
        self.query_one("#orb", BrailleOrb).energy = ENERGY[state]

    @work(thread=True, exclusive=True, group="engine")
    def load_engine(self) -> None:
        from iris.composition import CLI, build_engine, uses_api

        try:
            engine = build_engine(self.settings, TuiApprover(self), self.session, CLI)
        except Exception as exc:
            self.call_from_thread(self.add_notice, self.t("start_failed", error=exc))
            self.call_from_thread(self.query_one("#model", Static).update, self.t("no_model"))
            return
        backend = self.settings.llm_backend
        if backend == "local":
            label = self.t("model.local", model=self.settings.local_model)
        elif backend == "claude_code" or not uses_api(backend):
            label = "Claude Code"
        else:
            label = f"Claude\n{self.settings.api_model}"
        self.engine = engine
        self.model_label = label.replace("\n", " · ")
        self.call_from_thread(self.query_one("#model", Static).update, label)

    def ledger(self):
        from iris.composition import ledger_for

        if not hasattr(self, "_ledger"):
            self._ledger = ledger_for(self.settings)
        return self._ledger

    def show_usage(self) -> None:
        from datetime import datetime

        from iris.application.usage import compact

        ledger = self.ledger()
        today = ledger.totals(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        lines = [self.t("usage.conversation", tokens=compact(self.conversation_tokens)), self.t("usage.today", tokens=compact(today.tokens))]
        if today.cost > 0:
            lines.append(self.t("usage.cost", cost=f"{today.cost:.2f}"))
        self.query_one("#who", Static).update(ledger.user)
        self.query_one("#usage", Static).update("\n".join(lines))

    def show_usage_report(self) -> None:
        from iris.application.usage import compact

        ledger = self.ledger()
        rows = [self.t("usage.header"), "|---|---|---|---|---|"]
        any_cost = False
        for key, totals in ledger.periods():
            any_cost = any_cost or totals.cost > 0
            rows.append(f"| {self.t(PERIOD_KEYS[key])} | {totals.calls} | {compact(totals.input_tokens)} | {compact(totals.output_tokens)} | **{compact(totals.tokens)}** |")
        models = "\n".join(
            self.t("usage.model_line", model=model, tokens=compact(t.tokens), calls=t.calls, cost=f", US$ {t.cost:.2f}" if t.cost else "")
            for model, t in ledger.by_model()
        )
        note = f"\n\n{self.t('usage.free')}" if not any_cost else ""
        models_block = f"\n\n**{self.t('usage.models')}**\n\n{models}" if models else ""
        self.add_iris_text(f"**{self.t('usage.title', user=ledger.user)}**\n\n" + "\n".join(rows) + models_block + note)

    @work(thread=True, group="counts")
    def load_counts(self) -> None:
        try:
            import sqlite3

            from iris.knowledge.sqlite_memory import SQLiteMemory

            facts = len(SQLiteMemory(self.settings.memory_file).all())
            sources = 0
            if self.settings.library_db.exists():
                with sqlite3.connect(self.settings.library_db) as db:
                    sources = db.execute("SELECT count(*) FROM sources").fetchone()[0]
            self.call_from_thread(self.query_one("#facts", Static).update, self.t("facts", facts=facts, sources=sources))
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
        self.set_state("tool", describe(call, self.language).split(" · ")[0].lower())
        line = ToolLine(call, self.language)
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
        matches = [name for name, _ in COMMANDS if name.startswith(typed)]
        menu = self.menu()
        menu.clear_options()
        if not matches:
            self.hide_menu()
            return
        for name in matches:
            label = Text.assemble((f"/{name:<10}", "bold #e9b04c"), (self.t(f"cmd.{name}"), "#a0968a"))
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
        self.send(self.t(f"suggestion.{event.button.id.rsplit('-', 1)[1]}"))

    @on(Button.Pressed, "#yes")
    def confirm_yes(self) -> None:
        self.send(self.t("yes.text"))

    @on(Button.Pressed, "#no")
    def confirm_no(self) -> None:
        self.send(self.t("no.text"))

    def send(self, text: str) -> None:
        if self.busy:
            self.add_notice(self.t("busy"))
            return
        if self.engine is None:
            self.add_notice(self.t("not_ready"))
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
        from datetime import datetime

        started = datetime.now().replace(microsecond=0)
        self.session.turn += 1
        kwargs: dict[str, Callable] = {"on_text": self.stream}
        if "on_tool" in inspect.signature(self.engine.ask).parameters:
            kwargs["on_tool"] = self.tool_event
        try:
            answer = self.engine.ask(text, **kwargs)
            if not self.buffer.strip() and answer:
                self.buffer = answer
        except Exception as exc:
            self.buffer += "\n\n" + self.t("answer_failed", error=exc)
        self.call_from_thread(self.render_buffer)
        self.call_from_thread(self.set_busy, False)
        self.call_from_thread(self.load_counts)
        spent = self.ledger().totals(started)
        if spent.calls:
            self.conversation_tokens += spent.tokens
            self.call_from_thread(self.add_spent, spent)
        self.call_from_thread(self.show_usage)

    def add_spent(self, spent) -> None:
        from iris.application.usage import compact

        cost = f" · US$ {spent.cost:.4f}" if spent.cost else ""
        text = self.t("spent", tokens=compact(spent.tokens), input=compact(spent.input_tokens), output=compact(spent.output_tokens), cost=cost)
        self.mount_message(Static(text, classes="spent"))

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
            lines = "\n".join(f"- `/{n}` {self.t(f'cmd.{n}')}" for n, _ in COMMANDS)
            self.add_iris_text(f"**{self.t('help.title')}**\n\n{lines}\n\n{self.t('help.footer')}")
        elif name == "memory":
            self.show_memory()
        elif name == "remember" and arg:
            from iris.knowledge.sqlite_memory import SQLiteMemory

            fact = SQLiteMemory(self.settings.memory_file).remember(arg)
            self.add_notice(self.t("saved_fact", id=fact.id))
            self.load_counts()
        elif name == "forget" and arg.lstrip("#").isdigit():
            from iris.knowledge.sqlite_memory import SQLiteMemory

            forgotten = SQLiteMemory(self.settings.memory_file).forget(int(arg.lstrip("#")))
            self.add_notice(self.t("forgotten") if forgotten else self.t("fact_missing"))
            self.load_counts()
        elif name == "library":
            self.show_library()
        elif name == "learn" and arg:
            self.learn(arg)
        elif name == "usage":
            self.show_usage_report()
        elif name == "model":
            self.add_notice(self.t("model.now", model=self.model_label or self.t("loading")))
        elif name == "language" and normalize(arg) == arg.lower()[:2] and arg.lower()[:2] in LANGUAGES:
            self.change_language(arg.lower()[:2])
        elif name == "language":
            self.add_notice(self.t("language.options", options=", ".join(f"{code} ({label})" for code, label in LANGUAGES.items())))
        elif name == "key":
            self.manage_key(arg.lower())
        elif name in NEEDS_ARGUMENT:
            self.add_notice(self.t("missing_argument", example=self.t(f"cmd.{name}").split(": ")[-1].split(". ")[-1]))
        else:
            self.add_notice(self.t("unknown_command"))

    def manage_key(self, provider: str) -> None:
        from iris.infrastructure.secrets import PROVIDERS, get_secret, masked, set_secret

        if not provider:
            lines = [f"- **{name}**: " + (f"{self.t('key.set')} `{masked(get_secret(secret))}`" if get_secret(secret) else self.t("key.unset")) for name, (secret, _) in PROVIDERS.items()]
            self.add_iris_text(f"**{self.t('key.status')}**\n\n" + "\n".join(lines) + f"\n\n{self.t('key.usage')}")
            return
        if provider not in PROVIDERS:
            self.add_notice(self.t("key.unknown", options=", ".join(PROVIDERS)))
            return
        secret, site = PROVIDERS[provider]

        def saved(value: str | None) -> None:
            if value:
                set_secret(secret, value)
                self.add_notice(self.t("key.saved", provider=provider.title()))
                self.engine = None
                self.load_engine()

        self.push_screen(KeyScreen(provider, site, self.language), saved)

    def change_language(self, code: str) -> None:
        from iris.cli import save_setting

        save_setting(self.settings.settings_file, "IRIS_LANGUAGE", code)
        self.settings.language = code
        self.apply_language()
        self.add_notice(self.t("language.changed", language=LANGUAGES[code]))
        self.engine = None
        self.load_engine()

    def show_memory(self) -> None:
        from iris.knowledge.sqlite_memory import SQLiteMemory

        facts = SQLiteMemory(self.settings.memory_file).all()
        body = "\n".join(f"- `#{f.id}` {f.content}" for f in facts) or self.t("memory.empty")
        self.add_iris_text(f"**{self.t('memory.title')}**\n\n{body}")

    @work(thread=True, group="library")
    def show_library(self) -> None:
        from iris.composition import library_for

        sources = library_for(self.settings, index_in_background=False).sources()
        body = "\n".join(self.t("library.item", title=title, count=count, source=source) for title, source, count in sources)
        self.call_from_thread(self.add_iris_text, f"**{self.t('library.title')}**\n\n{body or self.t('library.empty')}")

    @work(thread=True, group="library")
    def learn(self, source: str) -> None:
        from iris.composition import library_for

        self.call_from_thread(self.add_notice, self.t("learning", source=source))
        result = library_for(self.settings, index_in_background=False).learn(source)
        self.call_from_thread(self.add_notice, result)
        self.call_from_thread(self.load_counts)

    def action_new_chat(self) -> None:
        if self.engine is not None and hasattr(self.engine, "reset"):
            self.engine.reset()
        self.conversation_tokens = 0
        self.show_usage()
        self.action_clear()
        self.add_notice(self.t("new_chat"))

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
