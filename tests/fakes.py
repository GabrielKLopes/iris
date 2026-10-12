from typing import Any

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel, Interaction, LLMResponse, Message, ToolCall


class ScriptedLLM:
    model = "fake"

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[tuple[str, list[Message]]] = []

    def generate(self, system: str, messages: list[Message], tools: list[Tool], on_text=None) -> LLMResponse:
        self.calls.append((system, list(messages)))
        response = self.responses.pop(0)
        if on_text and response.text:
            on_text(response.text)
        return response


class EchoTool(Tool):
    name = "echo"
    description = "Returns the given text"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    def run(self, tool_input: dict[str, Any]) -> str:
        return tool_input["text"]


class WriteTool(Tool):
    name = "restart"
    description = "Write action"
    input_schema = {"type": "object"}
    access = AccessLevel.WRITE

    def __init__(self):
        self.executed = False

    def run(self, tool_input: dict[str, Any]) -> str:
        self.executed = True
        return "ok"


class BrokenTool(Tool):
    name = "broken"
    description = "Always fails"
    input_schema = {"type": "object"}

    def run(self, tool_input: dict[str, Any]) -> str:
        raise RuntimeError("boom")


class StaticKnowledge:
    def __init__(self, documents: list[str]):
        self.documents = documents

    def search(self, query: str, limit: int = 5) -> list[str]:
        return self.documents[:limit]


class InMemoryRecorder:
    def __init__(self):
        self.interactions: list[Interaction] = []

    def record(self, interaction: Interaction) -> None:
        self.interactions.append(interaction)


class ApproveAll:
    def approve(self, call: ToolCall) -> bool:
        return True
