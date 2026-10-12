from typing import Any

from iris.agent.ports import MemoryStore, Tool
from iris.domain.models import AccessLevel


class RememberTool(Tool):
    name = "remember"
    description = (
        "Saves a lasting fact about the user or their work so it can be used in future conversations, "
        "e.g. their email address, city, preferences, servers or procedures. "
        "Use it whenever the user teaches something or answers a question about themselves."
    )
    input_schema = {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "Self-contained fact in Portuguese"}},
        "required": ["fact"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def run(self, tool_input: dict[str, Any]) -> str:
        fact = self.memory.remember(tool_input["fact"])
        return f"Saved fact #{fact.id}"


class SearchMemoryTool(Tool):
    name = "search_memory"
    description = "Searches what the user has taught before. Use it before asking the user for information."
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def run(self, tool_input: dict[str, Any]) -> str:
        found = self.memory.search(tool_input["query"], limit=10)
        return "\n".join(found) if found else "Nothing found in memory."


class ForgetTool(Tool):
    name = "forget"
    description = "Deletes a saved fact by id when the user says it is wrong or outdated."
    input_schema = {
        "type": "object",
        "properties": {"fact_id": {"type": "integer"}},
        "required": ["fact_id"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def run(self, tool_input: dict[str, Any]) -> str:
        return "Deleted" if self.memory.forget(int(tool_input["fact_id"])) else "Fact not found"
