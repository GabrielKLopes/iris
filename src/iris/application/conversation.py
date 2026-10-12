from iris.agent.loop import AgentLoop
from iris.domain.models import Message, Role


def trim_history(messages: list[Message], max_turns: int) -> list[Message]:
    starts = [i for i, m in enumerate(messages) if m.role is Role.USER and m.text and not m.tool_results]
    if len(starts) <= max_turns:
        return messages
    return messages[starts[-max_turns] :]


class Conversation:
    def __init__(self, loop: AgentLoop, max_turns: int = 15):
        self.loop = loop
        self.max_turns = max_turns
        self.history: list[Message] = []

    def ask(self, text: str, on_text=None, on_tool=None) -> str:
        interaction = self.loop.run(text, self.history, on_text=on_text, on_tool=on_tool)
        self.history = trim_history(list(interaction.messages), self.max_turns)
        return interaction.answer

    def reset(self) -> None:
        self.history = []
