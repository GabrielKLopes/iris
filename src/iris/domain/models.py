from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class AccessLevel(str, Enum):
    READ = "read"
    LOCAL = "local"
    WRITE = "write"


class Rating(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class Fact:
    id: int
    content: str
    created_at: datetime


@dataclass
class Interaction:
    question: str
    context: list[str]
    messages: list[Message]
    answer: str
    model: str
    started_at: datetime
    finished_at: datetime
    rating: Rating | None = None
    correction: str | None = None
