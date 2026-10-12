from __future__ import annotations

import fnmatch
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from send2trash import send2trash

from iris.application.intent import normalize

KNOWN_FOLDERS = {
    "downloads": "Downloads",
    "download": "Downloads",
    "documentos": "Documents",
    "documents": "Documents",
    "area de trabalho": "Desktop",
    "desktop": "Desktop",
    "imagens": "Pictures",
    "fotos": "Pictures",
    "videos": "Videos",
    "musicas": "Music",
    "projetos": "C:/projetos",
}


SKIPPED_DIRS = {"AppData", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "OneDrive", "Searches"}


class OutsideAllowedArea(ValueError):
    pass


class LocalFiles:
    def __init__(self, roots: list[Path] | None = None, home: Path | None = None):
        self.home = home or Path.home()
        self.roots = [r.resolve() for r in (roots or [self.home, Path("C:/projetos")])]

    def resolve(self, raw: str) -> Path:
        text = raw.strip().strip('"')
        known = KNOWN_FOLDERS.get(normalize(text))
        if known:
            path = Path(known) if ":" in known else self.home / known
        else:
            first, _, rest = text.replace("\\", "/").partition("/")
            alias = KNOWN_FOLDERS.get(normalize(first))
            if alias and rest:
                base = Path(alias) if ":" in alias else self.home / alias
                path = base / rest
            else:
                path = Path(os.path.expandvars(os.path.expanduser(text)))
                if not path.is_absolute():
                    path = self.home / path
        path = path.resolve()
        if not any(path == root or root in path.parents for root in self.roots):
            raise OutsideAllowedArea(f"{path} is outside the folders Iris may touch")
        return path

    @staticmethod
    def describe(path: Path) -> str:
        stat = path.stat()
        kind = "folder" if path.is_dir() else f"{stat.st_size / 1024 / 1024:.1f} MB"
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
        return f"{path.name} ({kind}, {modified})"

    def list(self, folder: str, limit: int = 40) -> str:
        path = self.resolve(folder)
        if not path.is_dir():
            return f"{path} is not a folder"
        entries = sorted(path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        lines = [self.describe(p) for p in entries[:limit]]
        more = f"\n... and {len(entries) - limit} more" if len(entries) > limit else ""
        return f"{path} has {len(entries)} items, newest first:\n" + "\n".join(lines) + more

    def find(self, pattern: str, folder: str = "~", limit: int = 30, seconds: float = 4.0) -> str:
        base = self.resolve(folder)
        glob = (pattern if any(c in pattern for c in "*?") else f"*{pattern}*").lower()
        deadline = time.monotonic() + seconds
        matches: list[Path] = []
        first = [self.home / n for n in ("Downloads", "Desktop", "Documents")] if base == self.home else []
        done: set[Path] = set()
        for start in [*first, base]:
            if not start.is_dir():
                continue
            for root, dirs, names in os.walk(start):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIPPED_DIRS and Path(root) / d not in done]
                for name in dirs + names:
                    if fnmatch.fnmatch(name.lower(), glob):
                        matches.append(Path(root) / name)
                if len(matches) >= limit or time.monotonic() > deadline:
                    break
            done.add(start)
            if len(matches) >= limit or time.monotonic() > deadline:
                break
            if matches and first and start == first[-1]:
                break
        if not matches:
            return f"Nothing matching '{pattern}' in {base}"
        return "\n".join(str(p) for p in matches[:limit])

    def create_folder(self, folder: str) -> str:
        path = self.resolve(folder)
        path.mkdir(parents=True, exist_ok=True)
        return f"Folder ready: {path}"

    def move(self, sources: list[str], destination: str) -> str:
        target = self.resolve(destination)
        moved = []
        for raw in sources:
            source = self.resolve(raw)
            if not source.exists():
                moved.append(f"missing: {source}")
                continue
            final = target / source.name if target.is_dir() else target
            shutil.move(str(source), str(final))
            moved.append(f"{source} -> {final}")
        return "\n".join(moved)

    def check_deletable(self, paths: list[str]) -> list[Path]:
        resolved = [self.resolve(p) for p in paths]
        for path in resolved:
            if path in self.roots or not path.exists():
                raise ValueError(f"Cannot delete {path}")
        return resolved

    def delete(self, paths: list[Path]) -> str:
        for path in paths:
            send2trash(str(path))
        return f"Sent {len(paths)} item(s) to the Recycle Bin"

    def read(self, raw: str, limit: int = 20000) -> str:
        path = self.resolve(raw)
        if not path.is_file():
            return f"{path} is not a file"
        text = path.read_text(encoding="utf-8", errors="replace")
        more = f"\n... ({len(text) - limit} more characters)" if len(text) > limit else ""
        return f"{path}:\n{text[:limit]}{more}"

    def write(self, raw: str, content: str, overwrite: bool = False) -> str:
        path = self.resolve(raw)
        if path.exists() and not overwrite:
            return f"{path} already exists. Ask the user before replacing it, then call again with overwrite true."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content.splitlines())} lines to {path}"

    def open(self, raw: str) -> str:
        path = self.resolve(raw)
        os.startfile(str(path))
        return f"Opened {path}"
