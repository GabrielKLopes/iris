from datetime import datetime, timezone

from iris.agent.guardrails import Guardrail
from iris.agent.ports import DatasetRecorder, KnowledgeBase, LLMProvider
from iris.agent.tools import ToolRegistry
from iris.domain.models import Interaction, Message, Role, ToolCall, ToolResult


class MaxStepsExceeded(RuntimeError):
    pass


class AgentLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        guardrail: Guardrail,
        knowledge: KnowledgeBase,
        recorder: DatasetRecorder,
        system_prompt: str,
        max_steps: int = 8,
        ledger=None,
    ):
        self.llm = llm
        self.tools = tools
        self.guardrail = guardrail
        self.knowledge = knowledge
        self.recorder = recorder
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.ledger = ledger

    def run(self, question: str, history: list[Message] | None = None, on_text=None, on_tool=None) -> Interaction:
        started_at = datetime.now(timezone.utc)
        context = self.knowledge.search(question)
        system = self._build_system(context)
        messages = [*(history or []), Message(Role.USER, question)]

        for _ in range(self.max_steps):
            response = self.llm.generate(system, messages, self.tools.all(), on_text=on_text)
            if self.ledger is not None and response.usage is not None:
                self.ledger.record(self.llm.model, response.usage)
            messages.append(Message(Role.ASSISTANT, response.text, list(response.tool_calls)))
            if not response.tool_calls:
                interaction = Interaction(
                    question=question,
                    context=context,
                    messages=messages,
                    answer=response.text,
                    model=self.llm.model,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                )
                self.recorder.record(interaction)
                return interaction
            results = [self._observed(call, on_tool) for call in response.tool_calls]
            messages.append(Message(Role.USER, tool_results=results))

        raise MaxStepsExceeded(f"Agent exceeded {self.max_steps} steps")

    def _build_system(self, context: list[str]) -> str:
        if not context:
            return self.system_prompt
        documents = "\n\n".join(f"<document>\n{item}\n</document>" for item in context)
        return f"{self.system_prompt}\n\n<knowledge>\n{documents}\n</knowledge>"

    def _observed(self, call: ToolCall, on_tool) -> ToolResult:
        if on_tool:
            on_tool("start", call, None)
        result = self._run_tool(call)
        if on_tool:
            on_tool("end", call, result)
        return result

    def _run_tool(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, f"Unknown tool: {call.name}", is_error=True)
        denial = self.guardrail.denial(tool, call)
        if denial:
            return ToolResult(call.id, denial, is_error=True)
        try:
            return ToolResult(call.id, tool.run(call.input))
        except Exception as exc:
            return ToolResult(call.id, f"Tool {call.name} failed: {exc}", is_error=True)
