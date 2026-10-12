from __future__ import annotations

import re
from pathlib import PurePath

from textual.widgets import Collapsible, Markdown

from iris.i18n import tr

MAX_LINES = 18
LANGUAGES = {
    ".yml": "yaml", ".yaml": "yaml", ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".json": "json", ".md": "markdown", ".sh": "bash", ".ps1": "powershell", ".sql": "sql", ".html": "html",
    ".css": "css", ".toml": "toml", ".ini": "ini", ".cs": "csharp", ".java": "java", ".go": "go", ".env": "bash",
}
NAMED = {"dockerfile": "dockerfile", "makefile": "makefile", "docker-compose.yml": "yaml"}
HIT = re.compile(r"^(?P<title>.+?) - (?P<url>https?://\S+)$")


def language_of(path: str) -> str:
    name = PurePath(path.replace("\\", "/")).name.lower()
    return NAMED.get(name) or LANGUAGES.get(PurePath(name).suffix, "text")


def trimmed(text: str, language: str) -> tuple[str, str]:
    lines = text.rstrip().splitlines()
    shown = "\n".join(lines[:MAX_LINES]).replace("```", "``​`")
    extra = len(lines) - MAX_LINES
    more = f"\n\n{tr(language, 'preview.more', count=extra)}" if extra > 0 else ""
    return shown, more


def fence(text: str, code_language: str, language: str) -> str:
    shown, more = trimmed(text, language)
    return f"```{code_language}\n{shown}\n```{more}"


def preview_for(call, result, language: str) -> Collapsible | None:
    if result.is_error:
        return None
    content = result.content or ""
    if call.name == "write_file":
        path = str(call.input.get("path", ""))
        body = fence(str(call.input.get("content", "")), language_of(path), language)
        lines = len(str(call.input.get("content", "")).splitlines())
        return Collapsible(Markdown(body), title=tr(language, "preview.lines", count=lines), collapsed=False, classes="preview")
    if call.name == "run_command":
        output = re.sub(r"^Exit code 0\n?", "", content).strip()
        if not output or output.startswith("Not run yet"):
            return None
        return Collapsible(Markdown(fence(output, "text", language)), title=str(call.input.get("command", ""))[:80], collapsed=False, classes="preview")
    if call.name == "web_search":
        hits = [HIT.match(line.strip()) for line in content.splitlines()]
        items = [f"- [{m['title'][:90]}]({m['url']})" for m in hits if m][:6]
        if not items:
            return None
        return Collapsible(Markdown("\n".join(items)), title=tr(language, "preview.sources", count=len(items)), collapsed=False, classes="preview")
    if call.name in ("read_file", "list_folder", "find_files", "search_library"):
        code_language = language_of(str(call.input.get("path", ""))) if call.name == "read_file" else "text"
        return Collapsible(Markdown(fence(content, code_language, language)), title=tr(language, "preview.result"), collapsed=True, classes="preview")
    return None
