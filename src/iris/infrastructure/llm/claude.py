from typing import Any

import anthropic

from iris.agent.ports import Tool
from iris.domain.models import LLMResponse, Message, ToolCall, Usage


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    converted = []
    for message in messages:
        blocks: list[dict[str, Any]] = []
        if message.text:
            blocks.append({"type": "text", "text": message.text})
        for call in message.tool_calls:
            blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.input})
        for result in message.tool_results:
            blocks.append(
                {"type": "tool_result", "tool_use_id": result.id, "content": result.content, "is_error": result.is_error}
            )
        if blocks:
            converted.append({"role": message.role.value, "content": blocks})
    return converted


def to_api_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]


def usage_of(response: Any) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    server = getattr(usage, "server_tool_use", None)
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        web_searches=(getattr(server, "web_search_requests", 0) or 0) if server else 0,
    )


def from_api_response(content: list[Any], usage: Usage | None = None) -> LLMResponse:
    texts, calls = [], []
    for block in content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(block.id, block.name, dict(block.input)))
    return LLMResponse("\n".join(texts).strip(), calls, usage)


def build_request(model: str, max_tokens: int, system: str, messages: list[Message], tools: list[Tool]) -> dict[str, Any]:
    api_tools = to_api_tools(tools)
    if api_tools:
        api_tools[-1] = {**api_tools[-1], "cache_control": {"type": "ephemeral"}}
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": to_api_messages(messages),
        "tools": api_tools,
    }


WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}


class ClaudeProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 512,
        extra: dict[str, Any] | None = None,
        server_tools: list[dict[str, Any]] | None = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.extra = extra or {}
        self.server_tools = server_tools or []

    def generate(self, system: str, messages: list[Message], tools: list[Tool], on_text=None) -> LLMResponse:
        request = {**build_request(self.model, self.max_tokens, system, messages, tools), **self.extra}
        if self.server_tools:
            request["tools"] = [*request["tools"], *self.server_tools]
        with self.client.messages.stream(**request) as stream:
            if on_text:
                for text in stream.text_stream:
                    on_text(text)
            response = stream.get_final_message()
        return from_api_response(response.content, usage_of(response))

