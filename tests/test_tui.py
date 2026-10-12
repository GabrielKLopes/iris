import asyncio

from iris.config import Settings
from iris.domain.models import ToolCall, ToolResult
from iris.tui.app import IrisApp, ToolLine


class FakeEngine:
    def __init__(self):
        self.questions = []

    def ask(self, text, on_text=None, on_tool=None):
        self.questions.append(text)
        call = ToolCall("c1", "delete_files", {"paths": ["C:/Users/u/Downloads/setup.exe"]})
        on_tool("start", call, None)
        on_tool("end", call, ToolResult("c1", "Nothing deleted yet. Ask the user. Confirmation code: ab12"))
        for piece in ["Posso mandar ", "o **setup.exe** ", "para a Lixeira?"]:
            on_text(piece)
        return "Posso mandar o setup.exe para a Lixeira?"

    def reset(self):
        self.questions.clear()


def make_app(tmp_path):
    app = IrisApp(Settings(data_dir=tmp_path, user_name="Ana"))
    app.load_engine = lambda: None
    app.engine = FakeEngine()
    return app


def test_conversation_streams_shows_tools_and_offers_confirmation(tmp_path):
    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.click("#prompt")
            await pilot.press(*"apaga o instalador", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            tools = list(app.query(ToolLine))
            assert len(tools) == 1 and tools[0].has_class("done")
            assert "Lixeira" in app.buffer
            assert app.query_one("#replies").has_class("visible")

            await pilot.pause()
            await pilot.click("#yes")
            await app.workers.wait_for_complete()
            assert app.engine.questions == ["apaga o instalador", "sim, pode"]

    asyncio.run(scenario())


def test_slash_commands(tmp_path):
    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.click("#prompt")
            await pilot.press(*"/remember moro em Recife", "enter")
            await pilot.press(*"/memory", "enter")
            await pilot.pause()
            text = " ".join(str(w.render()) for w in app.query("Static"))
            assert "Guardado como #1" in text

            await pilot.press(*"/new", "enter")
            await pilot.pause()
            assert app.engine.questions == []

    asyncio.run(scenario())


def test_history_with_arrow_keys(tmp_path):
    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.click("#prompt")
            await pilot.press(*"oi", "enter")
            await app.workers.wait_for_complete()
            await pilot.press("up")
            assert app.query_one("#prompt").value == "oi"

    asyncio.run(scenario())


def test_slash_opens_the_command_menu_and_completes(tmp_path):
    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.click("#prompt")
            await pilot.press("/")
            assert app.menu_visible() and app.menu().option_count == 10
            await pilot.press("r", "e")
            assert app.menu().option_count == 1
            await pilot.press("tab")
            assert app.query_one("#prompt").value == "/remember "
            await pilot.press(*"tenho um gato", "enter")
            await pilot.pause()
            assert "Guardado como #1" in " ".join(str(w.render()) for w in app.query("Static"))

            await pilot.press("/", "h", "enter")
            await pilot.pause()
            assert not app.menu_visible()

    asyncio.run(scenario())
