from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from iris.agent.ports import Tool
from iris.domain.models import AccessLevel


class FileSystem(Protocol):
    def list(self, folder: str) -> str: ...

    def find(self, pattern: str, folder: str = "~") -> str: ...

    def create_folder(self, folder: str) -> str: ...

    def move(self, sources: list[str], destination: str) -> str: ...

    def open(self, raw: str) -> str: ...

    def check_deletable(self, paths: list[str]) -> list[Path]: ...

    def delete(self, paths: list[Path]) -> str: ...

    def read(self, path: str) -> str: ...

    def write(self, path: str, content: str, overwrite: bool = False) -> str: ...


FOLDER_HINT = "Folder path or a known name: Downloads, Documentos, Area de Trabalho, Imagens, Projetos"


def _safe(action: Callable[[], str]) -> str:
    try:
        return action()
    except Exception as exc:
        return f"Failed: {exc}"


class ListFolderTool(Tool):
    name = "list_folder"
    description = "Lists what is inside one of the user's folders, newest first, with sizes and dates."
    input_schema = {"type": "object", "properties": {"folder": {"type": "string", "description": FOLDER_HINT}}, "required": ["folder"]}

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.list(tool_input["folder"]))


class FindFilesTool(Tool):
    name = "find_files"
    description = "Finds files or folders by name (part of the name or a pattern like *.pdf) inside a folder and its subfolders."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "folder": {"type": "string", "description": FOLDER_HINT + ". Defaults to the user folder."},
        },
        "required": ["pattern"],
    }

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.find(tool_input["pattern"], tool_input.get("folder", "~")))


class CreateFolderTool(Tool):
    name = "create_folder"
    description = "Creates a folder (and missing parent folders)."
    input_schema = {"type": "object", "properties": {"folder": {"type": "string", "description": FOLDER_HINT}}, "required": ["folder"]}
    access = AccessLevel.LOCAL

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.create_folder(tool_input["folder"]))


class MoveFilesTool(Tool):
    name = "move_files"
    description = "Moves or renames files and folders. Use full paths from list_folder or find_files. Tell the user what you moved."
    input_schema = {
        "type": "object",
        "properties": {
            "sources": {"type": "array", "items": {"type": "string"}},
            "destination": {"type": "string", "description": "Destination folder, or the new full name when renaming one item"},
        },
        "required": ["sources", "destination"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.move(tool_input["sources"], tool_input["destination"]))


class OpenPathTool(Tool):
    name = "open_path"
    description = "Opens a folder in Explorer or a file with its default app."
    input_schema = {"type": "object", "properties": {"path": {"type": "string", "description": FOLDER_HINT + ", or a file path"}}, "required": ["path"]}
    access = AccessLevel.LOCAL

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.open(tool_input["path"]))


class ReadFileTool(Tool):
    name = "read_file"
    description = "Reads a text file (config, code, log, notes) so you can explain, summarize or fix it."
    input_schema = {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}}, "required": ["path"]}

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.read(tool_input["path"]))


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Creates a text file such as a docker-compose.yml, script, note, list or email draft. Fails if the file exists; "
        "to replace an existing file, ask the user first and call again with overwrite true only after they agree."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full file path, or a known folder followed by the name, e.g. Projetos/app/docker-compose.yml"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "description": "Only after the user agreed to replace the existing file"},
        },
        "required": ["path", "content"],
    }
    access = AccessLevel.LOCAL

    def __init__(self, files: FileSystem):
        self.files = files

    def run(self, tool_input: dict[str, Any]) -> str:
        return _safe(lambda: self.files.write(tool_input["path"], tool_input["content"], bool(tool_input.get("overwrite"))))


class DeleteFilesTool(Tool):
    name = "delete_files"
    description = (
        "Sends files or folders to the Recycle Bin, in two steps. First call it with the paths only: nothing is deleted, "
        "you get a confirmation code and must ask the user out loud, naming what will be deleted. Only after they say yes "
        "in their next message, call it again with the same paths and the confirmation code."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}, "description": "Not needed when confirming"},
            "confirmation": {"type": "string", "description": "Code from the first call, only after the user agreed"},
        },
    }
    access = AccessLevel.LOCAL

    def __init__(self, files: FileSystem, current_turn: Callable[[], int]):
        self.files = files
        self.current_turn = current_turn
        self.pending: dict[str, tuple[tuple[str, ...], int]] = {}

    def run(self, tool_input: dict[str, Any]) -> str:
        code = tool_input.get("confirmation")
        if code and code in self.pending:
            return self._confirm(code)
        try:
            paths = self.files.check_deletable(tool_input["paths"])
        except Exception as exc:
            return f"Failed: {exc}"
        key = tuple(sorted(str(p) for p in paths))
        if not code:
            code = secrets.token_hex(3)
            self.pending[code] = (key, self.current_turn())
            names = ", ".join(p.name for p in paths[:10]) + (" ..." if len(paths) > 10 else "")
            return f"Nothing deleted yet. Ask the user if you may send {len(paths)} item(s) to the Recycle Bin: {names}. Confirmation code: {code}"
        return "Invalid confirmation code. Start again without a code and ask the user."

    def _confirm(self, code: str) -> str:
        key, asked_at = self.pending[code]
        if self.current_turn() <= asked_at:
            return "The user has not answered yet. Ask first and wait for the reply."
        del self.pending[code]
        return _safe(lambda: self.files.delete([Path(p) for p in key]))
