import pytest

from iris.agent.guardrails import DenyWrites, Guardrail
from iris.agent.loop import AgentLoop, MaxStepsExceeded
from iris.agent.tools import ToolRegistry
from iris.domain.models import LLMResponse, ToolCall
from fakes import ApproveAll, BrokenTool, EchoTool, InMemoryRecorder, ScriptedLLM, StaticKnowledge, WriteTool


def build(responses, tools=None, knowledge=None, approver=None, max_steps=8):
    llm = ScriptedLLM(responses)
    recorder = InMemoryRecorder()
    loop = AgentLoop(
        llm=llm,
        tools=ToolRegistry(tools or []),
        guardrail=Guardrail(approver or DenyWrites()),
        knowledge=knowledge or StaticKnowledge([]),
        recorder=recorder,
        system_prompt="system",
        max_steps=max_steps,
    )
    return loop, llm, recorder


def test_direct_answer_is_recorded():
    loop, _, recorder = build([LLMResponse("hello")])
    interaction = loop.run("hi")
    assert interaction.answer == "hello"
    assert recorder.interactions == [interaction]


def test_runs_tool_and_returns_result_to_model():
    loop, llm, _ = build(
        [LLMResponse("", [ToolCall("1", "echo", {"text": "pong"})]), LLMResponse("done")],
        tools=[EchoTool()],
    )
    interaction = loop.run("ping")
    assert interaction.answer == "done"
    result = llm.calls[1][1][-1].tool_results[0]
    assert result.content == "pong" and not result.is_error


def test_write_tool_denied_without_approval():
    tool = WriteTool()
    loop, llm, _ = build(
        [LLMResponse("", [ToolCall("1", "restart", {})]), LLMResponse("could not")],
        tools=[tool],
    )
    loop.run("restart it")
    assert not tool.executed
    assert llm.calls[1][1][-1].tool_results[0].is_error


def test_write_tool_runs_with_approval():
    tool = WriteTool()
    loop, _, _ = build(
        [LLMResponse("", [ToolCall("1", "restart", {})]), LLMResponse("ok")],
        tools=[tool],
        approver=ApproveAll(),
    )
    loop.run("restart it")
    assert tool.executed


def test_failure_and_unknown_tool_become_errors_for_model():
    loop, llm, _ = build(
        [
            LLMResponse("", [ToolCall("1", "broken", {}), ToolCall("2", "missing", {})]),
            LLMResponse("ok"),
        ],
        tools=[BrokenTool()],
    )
    loop.run("x")
    assert all(r.is_error for r in llm.calls[1][1][-1].tool_results)


def test_knowledge_goes_into_system_prompt():
    loop, llm, recorder = build([LLMResponse("ok")], knowledge=StaticKnowledge(["swarm runbook"]))
    loop.run("x")
    assert "swarm runbook" in llm.calls[0][0]
    assert recorder.interactions[0].context == ["swarm runbook"]


def test_max_steps():
    call = LLMResponse("", [ToolCall("1", "echo", {"text": "a"})])
    loop, _, recorder = build([call, call], tools=[EchoTool()], max_steps=2)
    with pytest.raises(MaxStepsExceeded):
        loop.run("x")
    assert recorder.interactions == []
