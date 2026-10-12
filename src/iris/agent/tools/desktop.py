from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel


class AppLauncher(Protocol):
    def launch(self, name: str) -> str: ...

    def close(self, name: str) -> str: ...

    def youtube(self, query: str, kind: str = "video") -> str: ...

    def open_url(self, url: str) -> str: ...


class DesktopKeys(Protocol):
    def media(self, action: str) -> str: ...

    def close_tab(self, match: str | None = None) -> str: ...


class Screen(Protocol):
    def describe(self, question: str, monitor: int | None = None) -> str: ...

    def click(self, target: str, monitor: int | None = None) -> str: ...


class LookAtScreenTool(Tool):
    name = "look_at_screen"
    description = (
        "Takes a screenshot of the monitor the user is using and tells what is on it. Use it whenever they refer to "
        "something on their screen ('esse vídeo', 'esse link', 'o que tá aparecendo')."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What you need to know about the screen"},
            "monitor": {"type": "integer", "description": "Monitor number, only if the user said which"},
        },
        "required": ["question"],
    }

    def __init__(self, screen: Screen):
        self.screen = screen

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.screen.describe(tool_input["question"], tool_input.get("monitor"))


class ClickOnScreenTool(Tool):
    name = "click_on_screen"
    description = (
        "Finds an element on the user's screen (a video, link, button, tab) by describing it, and clicks it. "
        "Describe it precisely, e.g. 'the second video thumbnail', 'the link Login at the top right'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "monitor": {"type": "integer", "description": "Monitor number, only if the user said which"},
        },
        "required": ["target"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, screen: Screen):
        self.screen = screen

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.screen.click(tool_input["target"], tool_input.get("monitor"))


class WindowController(Protocol):
    def move_to_screen(self, number: int) -> str: ...

    def request_exit(self, mode: str) -> None: ...


class ExitTool(Tool):
    name = "close_yourself"
    description = (
        "Closes your own window. mode 'hide' hides it and keeps listening for 'Iris' in the background "
        "('fecha', 'some', 'esconde'); mode 'quit' shuts Iris down completely ('encerra o processo', 'desliga')."
    )
    input_schema = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["hide", "quit"]}},
        "required": ["mode"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, window: WindowController):
        self.window = window

    def run(self, tool_input: dict[str, Any]) -> str:
        self.window.request_exit(tool_input["mode"])
        return "Will happen right after this answer; say goodbye in two or three words."


class OpenAppTool(Tool):
    name = "open_app"
    description = (
        "Opens an application installed on the user's Windows computer by its name, "
        "e.g. 'chrome', 'vscode', 'teams', 'calculadora', 'explorador de arquivos', 'terminal'. "
        "The request comes from speech recognition, so names can be misheard (e.g. 'crônio' or 'cromo' = Chrome, "
        "'times' = Teams): pass the real app name you think the user meant."
    )
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Real application name, e.g. Google Chrome"}},
        "required": ["name"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, launcher: AppLauncher):
        self.launcher = launcher

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.launcher.launch(tool_input["name"])


class YoutubeTool(Tool):
    name = "youtube"
    description = (
        "Opens YouTube in the browser: kind 'video' plays the first matching video, 'channel' opens a creator's channel, "
        "'search' shows the search results. Use it for anything about YouTube instead of open_url. "
        "Names come from speech recognition: fix misheard names using <knowledge> before searching."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search on YouTube"},
            "kind": {"type": "string", "enum": ["video", "channel", "search"]},
        },
        "required": ["query", "kind"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, launcher: AppLauncher):
        self.launcher = launcher

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.launcher.youtube(tool_input["query"], tool_input.get("kind", "video"))


class CloseTabTool(Tool):
    name = "close_tab"
    description = (
        "Closes one browser tab (Chrome or Edge): the current tab, or the tab whose title contains the given text, "
        "e.g. 'YouTube'. Use this, not close_app, whenever the user says 'aba'."
    )
    input_schema = {
        "type": "object",
        "properties": {"match": {"type": "string", "description": "Text from the tab title; omit for the current tab"}},
    }
    access = AccessLevel.LOCAL

    def __init__(self, keys: DesktopKeys):
        self.keys = keys

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.keys.close_tab(tool_input.get("match"))


class MediaControlTool(Tool):
    name = "media_control"
    description = "Controls whatever is playing (YouTube, Spotify...): pause or resume, next, previous, stop, volume up/down, mute."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop", "volume_up", "volume_down", "mute"]}
        },
        "required": ["action"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, keys: DesktopKeys):
        self.keys = keys

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.keys.media(tool_input["action"])


class CloseAppTool(Tool):
    name = "close_app"
    description = (
        "Closes a whole application with all its windows, like clicking its X, so the app can still ask to save. "
        "For a single browser tab use close_tab instead. "
        "Use the real app name, fixing speech recognition mistakes."
    )
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Real application name, e.g. Google Chrome"}},
        "required": ["name"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, launcher: AppLauncher):
        self.launcher = launcher

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.launcher.close(tool_input["name"])


class OpenUrlTool(Tool):
    name = "open_url"
    description = (
        "Opens a website or a web search in the default browser. "
        "Pass a full URL, or a search phrase to search on Google."
    )
    input_schema = {
        "type": "object",
        "properties": {"target": {"type": "string", "description": "URL or search phrase"}},
        "required": ["target"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, launcher: AppLauncher):
        self.launcher = launcher

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.launcher.open_url(tool_input["target"])


class MoveWindowTool(Tool):
    name = "move_to_monitor"
    description = "Moves Iris's own window to another monitor. Monitors are numbered from 1."
    input_schema = {
        "type": "object",
        "properties": {"monitor": {"type": "integer", "description": "Monitor number, starting at 1"}},
        "required": ["monitor"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, window: WindowController):
        self.window = window

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.window.move_to_screen(int(tool_input["monitor"]))
