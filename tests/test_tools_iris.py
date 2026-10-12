import json

from iris.agent.guardrails import DenyWrites, Guardrail
from iris.agent.tools.memory import ForgetTool, RememberTool, SearchMemoryTool
from iris.agent.tools.weather import WeatherTool
from iris.application.conversation import Conversation
from iris.domain.models import LLMResponse, ToolCall
from iris.infrastructure.llm.claude import to_api_messages
from iris.knowledge.sqlite_memory import SQLiteMemory
from test_loop import build


class FakeWeather:
    def current(self, city):
        return {"city": city, "temperature_c": 22}


def test_memory_tools_are_local_and_allowed_without_approval(tmp_path):
    memory = SQLiteMemory(tmp_path / "facts.db")
    guardrail = Guardrail(DenyWrites())
    remember = RememberTool(memory)
    assert guardrail.allows(remember, ToolCall("1", remember.name, {}))
    assert remember.run({"fact": "Meu email é g@x.com"}) == "Saved fact #1"
    assert "g@x.com" in SearchMemoryTool(memory).run({"query": "email"})
    assert ForgetTool(memory).run({"fact_id": 1}) == "Deleted"


def test_weather_tool_returns_service_data_as_json():
    result = json.loads(WeatherTool(FakeWeather()).run({"city": "Osasco"}))
    assert result == {"city": "Osasco", "temperature_c": 22}


def test_conversation_keeps_history_between_turns():
    loop, llm, _ = build([LLMResponse("Qual é o seu email?"), LLMResponse("Anotado!")])
    conversation = Conversation(loop)
    conversation.ask("ve meu email")
    conversation.ask("é g@x.com")
    second_call_messages = llm.calls[1][1]
    assert [m.text for m in second_call_messages] == ["ve meu email", "Qual é o seu email?", "é g@x.com"]


def test_claude_message_conversion_includes_tool_blocks():
    from iris.domain.models import Message, Role, ToolResult

    converted = to_api_messages(
        [
            Message(Role.USER, "clima?"),
            Message(Role.ASSISTANT, "", [ToolCall("t1", "get_weather", {"city": "Osasco"})]),
            Message(Role.USER, tool_results=[ToolResult("t1", "{}")]),
        ]
    )
    assert converted[1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "get_weather", "input": {"city": "Osasco"}}
    assert converted[2]["content"][0]["type"] == "tool_result"


def test_claude_request_caches_system_and_tools():
    from iris.infrastructure.llm.claude import build_request
    from iris.domain.models import Message, Role

    request = build_request("m", 512, "sys", [Message(Role.USER, "oi")], [WeatherTool(FakeWeather())])
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert request["messages"] == [{"role": "user", "content": [{"type": "text", "text": "oi"}]}]
