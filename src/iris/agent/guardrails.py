import json

from iris.agent.ports import Approver, Tool
from iris.application.content_policy import ContentPolicy
from iris.domain.models import AccessLevel, ToolCall


class Guardrail:
    def __init__(self, approver: Approver, policy: ContentPolicy | None = None):
        self.approver = approver
        self.policy = policy or ContentPolicy()

    def denial(self, tool: Tool, call: ToolCall) -> str | None:
        violation = self.policy.check(json.dumps(call.input, ensure_ascii=False))
        if violation:
            return f"Blocked by content policy ({violation.category}). Refuse briefly without repeating the request."
        if tool.access in (AccessLevel.READ, AccessLevel.LOCAL):
            return None
        return None if self.approver.approve(call) else "Denied: this action requires user approval"

    def allows(self, tool: Tool, call: ToolCall) -> bool:
        return self.denial(tool, call) is None


class DenyWrites:
    def approve(self, call: ToolCall) -> bool:
        return False
