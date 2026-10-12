import json
import uuid
from typing import Any

import httpx

from iris.agent.ports import Tool
from iris.domain.models import LLMResponse, Message, Role, ToolCall


def to_ollama_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if message.tool_results:
            converted.extend({"role": "tool", "content": result.content} for result in message.tool_results)
        elif message.role is Role.USER:
            converted.append({"role": "user", "content": message.text})
        else:
            entry: dict[str, Any] = {"role": "assistant", "content": message.text}
            if message.tool_calls:
                entry["tool_calls"] = [{"function": {"name": c.name, "arguments": c.input}} for c in message.tool_calls]
            converted.append(entry)
    return converted


def to_ollama_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]


class OllamaProvider:
    def __init__(self, model: str, host: str = "http://127.0.0.1:11434", timeout: float = 120.0):
        self.model = model
        self.host = host.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def generate(self, system: str, messages: list[Message], tools: list[Tool], on_text=None) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": to_ollama_messages(system, messages),
            "tools": to_ollama_tools(tools),
            "stream": True,
            "options": {"temperature": 0.3},
        }
        texts: list[str] = []
        calls: list[ToolCall] = []
        with self.client.stream("POST", f"{self.host}/api/chat", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                message = chunk.get("message") or {}
                if message.get("content"):
                    texts.append(message["content"])
                    if on_text:
                        on_text(message["content"])
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments or "{}")
                    calls.append(ToolCall(uuid.uuid4().hex[:12], function.get("name", ""), arguments))
        return LLMResponse("".join(texts).strip(), calls)
