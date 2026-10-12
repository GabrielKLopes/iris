from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel


class SearchEngine(Protocol):
    def search(self, query: str) -> str: ...


class Library(Protocol):
    def search(self, query: str) -> str: ...

    def learn(self, source: str) -> str: ...


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Searches the web for current information (news, prices, releases, documentation) and returns titles, links "
        "and snippets. Use it when the answer may have changed recently or you are not sure; answer from the results "
        "and mention the source briefly."
    )
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search terms, in the language most likely to find good results"}},
        "required": ["query"],
    }

    def __init__(self, engine: SearchEngine):
        self.engine = engine

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.engine.search(tool_input["query"])


class SearchLibraryTool(Tool):
    name = "search_library"
    description = (
        "Searches the user's library: websites and documents the user asked you to learn. Returns the most relevant "
        "excerpts with their source. Use it first for questions about topics the user has taught you."
    )
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def __init__(self, library: Library):
        self.library = library

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.library.search(tool_input["query"])


class LearnUrlTool(Tool):
    name = "learn_url"
    description = (
        "Reads a website, a local document or a whole folder of documents and saves it in the user's library so you can use it later. "
        "Pass a URL, a file or folder path, or 'current_page' when the user says 'aprende esse site' about the page open in the browser."
    )
    input_schema = {
        "type": "object",
        "properties": {"source": {"type": "string", "description": "URL, file or folder path, or current_page"}},
        "required": ["source"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, library: Library):
        self.library = library

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.library.learn(tool_input["source"])
