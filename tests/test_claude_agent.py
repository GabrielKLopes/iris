import asyncio

from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage

from iris.agent.guardrails import DenyWrites, Guardrail
from iris.domain.models import Role
from iris.infrastructure.llm.claude_agent import build_prompt, collect_messages, wrap_tool
from fakes import BrokenTool, EchoTool, WriteTool


def run_handler(tool, args):
    wrapped = wrap_tool(tool, Guardrail(DenyWrites()))
    return asyncio.run(wrapped.handler(args))


def test_wrapped_tool_runs_and_returns_text():
    assert run_handler(EchoTool(), {"text": "pong"}) == {"content": [{"type": "text", "text": "pong"}]}


def test_wrapped_write_tool_is_denied_without_approval():
    tool = WriteTool()
    result = run_handler(tool, {})
    assert result["is_error"] and not tool.executed


def test_wrapped_tool_failure_becomes_error():
    assert run_handler(BrokenTool(), {})["is_error"]


def test_build_prompt_adds_knowledge():
    assert build_prompt("oi", []) == "oi"
    assert "[#1] mora em Osasco" in build_prompt("clima?", ["[#1] mora em Osasco"])


def test_collect_messages_maps_tool_calls_and_answer():
    stream = [
        AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__iris__get_weather", input={"city": "Osasco"})], model="haiku"),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": "22C"}], is_error=False)]),
        AssistantMessage(content=[TextBlock(text="Está 22 graus em Osasco.")], model="haiku"),
    ]
    messages, answer, _ = collect_messages("clima?", stream)
    assert answer == "Está 22 graus em Osasco."
    assert messages[1].tool_calls[0].name == "get_weather"
    assert messages[2].role is Role.USER and messages[2].tool_results[0].content == "22C"
