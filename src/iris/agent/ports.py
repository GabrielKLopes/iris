from abc import ABC, abstractmethod
from typing import Any, Protocol

from iris.domain.models import AccessLevel, Fact, Interaction, LLMResponse, Message, ToolCall


class Tool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    access: AccessLevel = AccessLevel.READ

    @abstractmethod
    def run(self, tool_input: dict[str, Any]) -> str: ...


class LLMProvider(Protocol):
    model: str

    def generate(self, system: str, messages: list[Message], tools: list[Tool], on_text=None) -> LLMResponse: ...


class KnowledgeBase(Protocol):
    def search(self, query: str, limit: int = 5) -> list[str]: ...


class MemoryStore(KnowledgeBase, Protocol):
    def remember(self, content: str) -> Fact: ...

    def forget(self, fact_id: int) -> bool: ...

    def all(self) -> list[Fact]: ...


class WeatherService(Protocol):
    def current(self, city: str) -> dict[str, Any]: ...


class DatasetRecorder(Protocol):
    def record(self, interaction: Interaction) -> None: ...


class Approver(Protocol):
    def approve(self, call: ToolCall) -> bool: ...
