from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel, Rating


class FeedbackStore(Protocol):
    def rate_last(self, rating: str, correction: str | None = None) -> str: ...


class RateAnswerTool(Tool):
    name = "rate_last_answer"
    description = (
        "Saves the user's feedback about your previous answer, used later to train your own model. "
        "Call it when they say an answer was good or bad (e.g. 'boa resposta', 'isso tá errado'). "
        "When they say what the right answer would be, pass it as correction."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "rating": {"type": "string", "enum": [r.value for r in Rating]},
            "correction": {"type": "string", "description": "The answer the user says would be right"},
        },
        "required": ["rating"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, store: FeedbackStore):
        self.store = store

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.store.rate_last(tool_input["rating"], tool_input.get("correction"))
