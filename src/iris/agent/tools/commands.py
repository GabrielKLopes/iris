import re
import secrets
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel

READ_ONLY = re.compile(
    r"""^\s*(
        (get|test|measure|resolve|select|find)-\w+ |
        dir | ls | gci | cat | type | echo | write-output | whoami | hostname | ipconfig | ping | nslookup | tracert |
        systeminfo | tasklist | netstat | where(\.exe)? | wsl\s+(-l|--list) |
        git\s+(-C\s+("[^"]+"|\S+)\s+)?(status|log|diff|branch|show|remote|rev-parse|describe|blame|shortlog|tag\s*$) |
        docker\s+(ps|images|logs|inspect|version|info|stats\s+--no-stream|compose\s+(ps|logs|config)|context\s+ls|node\s+ls|service\s+(ls|ps|logs|inspect)|stack\s+(ls|ps|services)) |
        kubectl\s+(get|describe|logs|top|version|config\s+(get-contexts|current-context)) |
        (python|node|npm|git|docker|kubectl|az|dotnet|java)\s+(--version|-v|version)
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)
PIPE_SAFE = re.compile(r"^\s*(select-object|where-object|sort-object|format-\w+|measure-object|out-string|findstr|select-string|group-object|\w+\s*\|)\b", re.IGNORECASE)
UNSAFE = re.compile(r"[;&>`]|\$\(|\b(remove|set|new|stop|start|restart|invoke|clear|rename|move|copy)-", re.IGNORECASE)


LEADING_CD = re.compile(r"""^\s*(?:cd|set-location|sl|pushd)\s+(?:"([^"]+)"|'([^']+)'|([^&;"']+?))\s*(?:&&|;)\s*(.+)$""", re.IGNORECASE | re.DOTALL)


def split_working_directory(command: str, default: Path) -> tuple[str, Path]:
    match = LEADING_CD.match(command)
    if not match:
        return command, default
    folder = Path(next(g for g in match.groups()[:3] if g))
    return (match.group(4).strip(), folder) if folder.is_dir() else (command, default)


def is_read_only(command: str) -> bool:
    if UNSAFE.search(command):
        return False
    first, *rest = command.split("|")
    return bool(READ_ONLY.match(first)) and all(PIPE_SAFE.match(part) for part in rest)


def run_powershell(command: str, cwd: Path, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; {command}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s"
    output = (result.stdout + ("\n" + result.stderr if result.stderr.strip() else "")).strip()
    if len(output) > 3000:
        output = output[:3000] + f"\n... ({len(output) - 3000} more characters)"
    return f"Exit code {result.returncode}\n{output}"


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Runs a PowerShell command on the user's computer (working folder C:\\projetos) and returns its output. "
        "Read-only commands (git status, docker ps, kubectl get, Get-*, ping, ipconfig...) run right away. "
        "Anything else returns a confirmation code instead: tell the user exactly what the command will do, ask them, "
        "and only after they say yes in their next message call again with the same command and the code. "
        "Never touch production or homologation (prod/hml) environments."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "PowerShell 5.1 command (no && operator)"},
            "folder": {"type": "string", "description": "Working folder, default C:/projetos"},
            "confirmation": {"type": "string", "description": "Code from the previous call, only after the user agreed"},
        },
        "required": ["command"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, current_turn: Callable[[], int], cwd: Path = Path("C:/projetos"), runner=run_powershell):
        self.current_turn = current_turn
        self.cwd = cwd
        self.runner = runner
        self.pending: dict[str, tuple[str, int]] = {}

    def run(self, tool_input: dict[str, Any]) -> str:
        default = Path(tool_input["folder"]) if tool_input.get("folder") else self.cwd
        command, cwd = split_working_directory(tool_input["command"].strip(), default)
        if not cwd.is_dir():
            return f"Folder not found: {cwd}"
        code = tool_input.get("confirmation")
        if is_read_only(command):
            return self.runner(command, cwd)
        if not code:
            code = secrets.token_hex(3)
            self.pending[code] = (f"{cwd}>{command}", self.current_turn())
            return f"Not run yet. Ask the user if you may run: {command} (in {cwd}). Confirmation code: {code}"
        pending = self.pending.get(code)
        if pending is None or pending[0] != f"{cwd}>{command}":
            return "Invalid confirmation code. Start again without a code and ask the user."
        if self.current_turn() <= pending[1]:
            return "The user has not answered yet. Ask first and wait for the reply."
        del self.pending[code]
        return self.runner(command, cwd)
