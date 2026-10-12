from iris.domain.models import Message, Role, ToolCall, ToolResult
from iris.infrastructure.llm.ollama import to_ollama_messages


def test_converts_history_with_tool_calls_and_results():
    messages = [
        Message(Role.USER, "abre o chrome"),
        Message(Role.ASSISTANT, "", [ToolCall("1", "open_app", {"name": "Google Chrome"})]),
        Message(Role.USER, tool_results=[ToolResult("1", "Opened Google Chrome")]),
        Message(Role.ASSISTANT, "Abri o Chrome."),
    ]
    converted = to_ollama_messages("system", messages)
    assert [m["role"] for m in converted] == ["system", "user", "assistant", "tool", "assistant"]
    assert converted[2]["tool_calls"][0]["function"] == {"name": "open_app", "arguments": {"name": "Google Chrome"}}
