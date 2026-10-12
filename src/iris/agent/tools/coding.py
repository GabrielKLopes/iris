import secrets
from collections.abc import Callable
from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel


class CodeWorker(Protocol):
    jobs: dict

    def analyze(self, question: str) -> str: ...

    def start(self, instruction: str): ...

    def apply(self, job_id: str) -> str: ...

    def discard(self, job_id: str) -> str: ...


class AnalyzeOwnCodeTool(Tool):
    name = "analyze_own_code"
    description = (
        "Reads your own source code (the Iris project) to answer how something in you works or where it is implemented. "
        "Takes up to a minute."
    )
    input_schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}

    def __init__(self, worker: CodeWorker):
        self.worker = worker

    def run(self, tool_input: dict[str, Any]) -> str:
        return self.worker.analyze(tool_input["question"])


class StartCodeChangeTool(Tool):
    name = "start_code_change"
    description = (
        "Starts changing your own code in the background on a separate git branch, to add a feature or fix a behavior "
        "the user asked for. Write a complete, specific instruction in English. You will be told when it is done; "
        "nothing changes in the running Iris until the user approves applying it."
    )
    input_schema = {"type": "object", "properties": {"instruction": {"type": "string"}}, "required": ["instruction"]}
    access = AccessLevel.LOCAL

    def __init__(self, worker: CodeWorker):
        self.worker = worker

    def run(self, tool_input: dict[str, Any]) -> str:
        job = self.worker.start(tool_input["instruction"])
        return f"Started change {job.id} on branch {job.branch}. It runs in the background; you will announce when it is done."


class CodeChangesStatusTool(Tool):
    name = "code_changes_status"
    description = "Lists the changes to your own code that are running, ready to apply, failed or applied."
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, worker: CodeWorker):
        self.worker = worker

    def run(self, tool_input: dict[str, Any]) -> str:
        if not self.worker.jobs:
            return "No code changes yet"
        return "\n".join(
            f"{job.id}: {job.status} | {job.instruction[:80]} | tests {job.tests or '-'} | files {', '.join(job.changed_files) or '-'} | {job.summary[:200]}"
            for job in self.worker.jobs.values()
        )


class ApplyCodeChangeTool(Tool):
    name = "apply_code_change"
    description = (
        "Applies a ready change to your own code and restarts you, in two steps. First call with the job id: you get a "
        "confirmation code and must ask the user. Only after they say yes in their next message, call again with the code. "
        "Use discard instead when they do not want the change."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "confirmation": {"type": "string"},
            "discard": {"type": "boolean", "description": "True to throw the change away instead"},
        },
        "required": ["job_id"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, worker: CodeWorker, current_turn: Callable[[], int], restart: Callable[[], None]):
        self.worker = worker
        self.current_turn = current_turn
        self.restart = restart
        self.pending: dict[str, tuple[str, int]] = {}

    def run(self, tool_input: dict[str, Any]) -> str:
        job_id = tool_input["job_id"]
        if tool_input.get("discard"):
            return self.worker.discard(job_id)
        code = tool_input.get("confirmation")
        if not code:
            code = secrets.token_hex(3)
            self.pending[code] = (job_id, self.current_turn())
            return f"Not applied yet. Ask the user if you may apply change {job_id} and restart. Confirmation code: {code}"
        pending = self.pending.get(code)
        if pending is None or pending[0] != job_id:
            return "Invalid confirmation code. Start again without a code and ask the user."
        if self.current_turn() <= pending[1]:
            return "The user has not answered yet. Ask first and wait for the reply."
        del self.pending[code]
        result = self.worker.apply(job_id)
        if result.startswith("Applied"):
            self.restart()
            return result + ". You will restart right after this answer; say goodbye in a few words."
        return result
