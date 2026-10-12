import asyncio
import logging
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk import tool as sdk_tool

from iris.agent.guardrails import Guardrail
from iris.agent.ports import DatasetRecorder, KnowledgeBase, Tool
from iris.agent.tools import ToolRegistry
from iris.domain.models import Interaction, Message, Role, ToolCall, ToolResult

log = logging.getLogger(__name__)


def _hide_console_windows() -> None:
    import subprocess
    import sys

    import anyio

    if sys.platform != "win32" or getattr(anyio.open_process, "_iris_hidden", False):
        return
    original = anyio.open_process

    async def open_process_hidden(*args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        return await original(*args, **kwargs)

    open_process_hidden._iris_hidden = True
    anyio.open_process = open_process_hidden


_hide_console_windows()

SERVER_NAME = "iris"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"


def wrap_tool(tool: Tool, guardrail: Guardrail):
    @sdk_tool(tool.name, tool.description, tool.input_schema)
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        tool_input = dict(args)
        denial = guardrail.denial(tool, ToolCall("sdk", tool.name, tool_input))
        if denial:
            return {"content": [{"type": "text", "text": denial}], "is_error": True}
        try:
            output = await asyncio.to_thread(tool.run, tool_input)
        except Exception as exc:
            return {"content": [{"type": "text", "text": f"Tool {tool.name} failed: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": output}]}

    return handler


def build_prompt(question: str, context: list[str]) -> str:
    if not context:
        return question
    documents = "\n".join(context)
    return f"<knowledge>\n{documents}\n</knowledge>\n\n{question}"


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
    return "" if content is None else str(content)


def collect_messages(question: str, stream: Iterable[Any]) -> tuple[list[Message], str, ResultMessage | None]:
    messages = [Message(Role.USER, question)]
    answer, result = "", None
    for item in stream:
        if isinstance(item, AssistantMessage):
            texts = [b.text for b in item.content if isinstance(b, TextBlock)]
            calls = [
                ToolCall(b.id, b.name.removeprefix(TOOL_PREFIX), dict(b.input))
                for b in item.content
                if isinstance(b, ToolUseBlock)
            ]
            text = "\n".join(texts).strip()
            messages.append(Message(Role.ASSISTANT, text, calls))
            if text:
                answer = text
        elif isinstance(item, UserMessage) and isinstance(item.content, list):
            results = [
                ToolResult(b.tool_use_id, _block_text(b.content), bool(b.is_error))
                for b in item.content
                if isinstance(b, ToolResultBlock)
            ]
            if results:
                messages.append(Message(Role.USER, tool_results=results))
        elif isinstance(item, ResultMessage):
            result = item
    return messages, answer, result


class ClaudeAgentEngine:
    def __init__(
        self,
        tools: ToolRegistry,
        guardrail: Guardrail,
        knowledge: KnowledgeBase,
        recorder: DatasetRecorder,
        system_prompt: str,
        model: str,
        max_turns: int,
        cwd: Path,
    ):
        self.knowledge = knowledge
        self.recorder = recorder
        self.model = model
        cwd.mkdir(parents=True, exist_ok=True)
        server = create_sdk_mcp_server(SERVER_NAME, tools=[wrap_tool(t, guardrail) for t in tools.all()])
        self.options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            tools=[],
            mcp_servers={SERVER_NAME: server},
            strict_mcp_config=True,
            allowed_tools=[f"{TOOL_PREFIX}{t.name}" for t in tools.all()],
            model=model,
            max_turns=max_turns,
            cwd=str(cwd),
            setting_sources=[],
            include_partial_messages=True,
        )
        self._client: ClaudeSDKClient | None = None
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def ask(self, question: str, on_text=None) -> str:
        return asyncio.run_coroutine_threadsafe(self._ask(question, on_text), self._loop).result()

    def reset(self) -> None:
        asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop).result()

    async def _connect(self) -> ClaudeSDKClient:
        if self._client is None:
            self._client = ClaudeSDKClient(options=self.options)
            await self._client.connect()
        return self._client

    async def _receive(self, prompt: str, on_text) -> list[Any]:
        client = await self._connect()
        await client.query(prompt)
        items = []
        async for item in client.receive_response():
            if isinstance(item, StreamEvent):
                delta = item.event.get("delta") or {}
                if on_text and item.event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    on_text(delta.get("text", ""))
                continue
            items.append(item)
        return items

    async def _exchange(self, prompt: str, on_text=None) -> list[Any]:
        try:
            return await self._receive(prompt, on_text)
        except Exception:
            log.warning("Claude Code session lost, reconnecting", exc_info=True)
            await self._drop()
            return await self._receive(prompt, on_text)

    async def _drop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _ask(self, question: str, on_text=None) -> str:
        started_at = datetime.now(timezone.utc)
        context = self.knowledge.search(question)
        stream = await self._exchange(build_prompt(question, context), on_text)
        messages, answer, result = collect_messages(question, stream)
        if result is not None and result.is_error:
            raise RuntimeError(result.result or "Claude Code returned an error")
        self.recorder.record(
            Interaction(
                question=question,
                context=context,
                messages=messages,
                answer=answer,
                model=f"claude-code:{self.model}",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return answer

    async def _disconnect(self) -> None:
        await self._drop()
