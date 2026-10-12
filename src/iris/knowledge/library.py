from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from iris.infrastructure.web.pages import fetch_text, page_text
from iris.knowledge.embeddings import Embedder

WORD = re.compile(r"\w{3,}", re.UNICODE)
FENCE = re.compile(r"(```.*?```)", re.DOTALL)
TEXT_SUFFIXES = {
    ".md", ".txt", ".rst", ".pdf", ".html", ".htm", ".json", ".yaml", ".yml", ".toml", ".ini", ".csv",
    ".py", ".ts", ".tsx", ".js", ".cs", ".java", ".go", ".sql", ".sh", ".ps1",
}
SKIPPED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
MAX_FOLDER_FILES = 300
MAX_FILE_BYTES = 5 * 1024 * 1024
RRF_K = 60
KEYWORD_WEIGHT = 0.8
VECTOR_WEIGHT = 1.0
STOPWORDS = set("""
como que qual quais quando onde porque por para pra pro com sem sobre entre ate desde antes depois minha meu meus minhas sua seu seus suas nossa nosso
uma umas uns dos das nos nas num numa esse essa esses essas este esta isso isto aquele aquela aquilo ele ela eles elas voce voces
tem ter ser estar esta estou foi vai vou faz faco fazer pode posso tambem mais menos muito muita bem mas entao ainda
the and for with what when where which who how why does did are was were this that these those your you can could would should
from into about have has had will just than then them they there their
""".split())


def normalize_word(word: str) -> str:
    return unicodedata.normalize("NFKD", word.lower()).encode("ascii", "ignore").decode()


def blocks(text: str) -> list[str]:
    result = []
    for part in FENCE.split(text):
        if part.startswith("```"):
            result.append(part.strip())
        else:
            result.extend(p.strip() for p in re.split(r"\n\s*\n", part) if p.strip())
    return result


def chunks(text: str, size: int = 900, overlap: int = 220) -> list[str]:
    parts: list[str] = []
    current = ""
    for block in blocks(text):
        if current and len(current) + len(block) > size:
            parts.append(current)
            tail = current[-overlap:]
            current = tail[tail.find(" ") + 1 :] if " " in tail else ""
        current = f"{current}\n\n{block}".strip()
        while len(current) > size * 2 and not current.startswith("```"):
            parts.append(current[:size])
            current = current[size - overlap :]
    if current:
        parts.append(current)
    return parts


def read_document(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return path.stem, "\n\n".join(page.extract_text() or "" for page in reader.pages)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        title, body = page_text(text)
        return title or path.stem, body
    if path.suffix.lower() not in (".md", ".txt", ".rst", ".pdf"):
        language = path.suffix.lstrip(".")
        return path.name, f"```{language}\n{text}\n```" if len(text) < 6000 else text
    return path.stem, text


def folder_files(folder: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS and not d.startswith(".")]
        for name in names:
            path = Path(root) / name
            if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= MAX_FILE_BYTES:
                found.append(path)
                if len(found) >= MAX_FOLDER_FILES:
                    return found
    return found


class SQLiteLibrary:
    def __init__(
        self,
        db_path: Path,
        resolve_path: Callable[[str], Path],
        current_url: Callable[[], str | None] = lambda: None,
        embedder: Embedder | None = None,
    ):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.lock = threading.Lock()
        self.resolve_path = resolve_path
        self.current_url = current_url
        self.embedder = embedder
        self.vectors = False
        with self.lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, source TEXT UNIQUE, title TEXT, learned_at TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
                    source_id UNINDEXED, title, text, tokenize = 'unicode61 remove_diacritics 2'
                );
                """
            )
            if embedder is not None:
                self.vectors = self._enable_vectors(embedder.dimensions)

    def _enable_vectors(self, dimensions: int) -> bool:
        try:
            import sqlite_vec

            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            self.db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS passage_vectors USING vec0(embedding float[{dimensions}])")
            return True
        except Exception as exc:
            logging.warning("Vector search disabled, keyword search only: %s", exc)
            return False

    def learn(self, source: str) -> str:
        source = source.strip()
        if source == "current_page":
            url = self.current_url()
            if not url:
                return "Could not read the address of the page open in the browser. Ask the user for the link."
            source = url
        if source.startswith(("http://", "https://")):
            try:
                title, text = fetch_text(source)
            except Exception as exc:
                return f"Could not open {source}: {exc}"
            return self._store(source, title, text)
        path = self.resolve_path(source)
        if path.is_dir():
            return self._learn_folder(path)
        if not path.is_file():
            return f"{path} is not a file or folder"
        title, text = read_document(path)
        return self._store(str(path), title, text)

    def _learn_folder(self, folder: Path) -> str:
        files = folder_files(folder)
        if not files:
            return f"No readable documents in {folder}"
        saved = 0
        for path in files:
            try:
                title, text = read_document(path)
                if text.strip():
                    self._store(str(path), title, text)
                    saved += 1
            except Exception as exc:
                logging.warning("Could not learn %s: %s", path, exc)
        limit = f" (stopped at {MAX_FOLDER_FILES} files)" if len(files) >= MAX_FOLDER_FILES else ""
        return f"Saved {saved} documents from {folder} to the library{limit}"

    def _store(self, source: str, title: str, text: str) -> str:
        parts = chunks(text)
        if not parts:
            return f"Could not find readable text in {source}"
        title = title or source
        vectors = self._embed([f"{title}\n{p}" for p in parts]) if self.vectors else None
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM sources WHERE source = ?", (source,)).fetchone()
            if row:
                source_id = row[0]
                self._delete_passages(source_id)
                self.db.execute("UPDATE sources SET title = ?, learned_at = ? WHERE id = ?", (title, now, source_id))
            else:
                source_id = self.db.execute("INSERT INTO sources (source, title, learned_at) VALUES (?, ?, ?)", (source, title, now)).lastrowid
            for index, part in enumerate(parts):
                rowid = self.db.execute("INSERT INTO passages (source_id, title, text) VALUES (?, ?, ?)", (source_id, title, part)).lastrowid
                if vectors is not None:
                    self.db.execute("INSERT INTO passage_vectors (rowid, embedding) VALUES (?, ?)", (rowid, vectors[index].tobytes()))
        return f"Saved '{title}' ({source}) to the library: {len(parts)} excerpts"

    def _delete_passages(self, source_id: int) -> None:
        if self.vectors:
            self.db.execute("DELETE FROM passage_vectors WHERE rowid IN (SELECT rowid FROM passages WHERE source_id = ?)", (source_id,))
        self.db.execute("DELETE FROM passages WHERE source_id = ?", (source_id,))

    def _embed(self, texts: list[str]):
        try:
            return self.embedder.embed(texts)
        except Exception as exc:
            logging.warning("Embedding failed, keeping keyword search only for this item: %s", exc)
            return None

    def index_missing(self, batch: int = 64) -> int:
        if not self.vectors:
            return 0
        done = 0
        while True:
            with self.lock:
                rows = self.db.execute(
                    "SELECT p.rowid, p.title, p.text FROM passages p WHERE p.rowid NOT IN (SELECT rowid FROM passage_vectors) LIMIT ?",
                    (batch,),
                ).fetchall()
            if not rows:
                return done
            vectors = self._embed([f"{title}\n{text}" for _, title, text in rows])
            if vectors is None:
                return done
            with self.lock, self.db:
                self.db.executemany(
                    "INSERT INTO passage_vectors (rowid, embedding) VALUES (?, ?)",
                    [(rowid, vectors[i].tobytes()) for i, (rowid, _, _) in enumerate(rows)],
                )
            done += len(rows)

    def _keyword_ids(self, query: str, limit: int) -> list[int]:
        words = [w for w in WORD.findall(query) if normalize_word(w) not in STOPWORDS]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT rowid FROM passages WHERE passages MATCH ? ORDER BY bm25(passages) LIMIT ?", (match, limit))]

    def _vector_ids(self, query: str, limit: int) -> list[int]:
        if not self.vectors:
            return []
        vector = self._embed([query])
        if vector is None:
            return []
        with self.lock:
            return [
                r[0]
                for r in self.db.execute(
                    "SELECT rowid FROM passage_vectors WHERE embedding MATCH ? AND k = ? ORDER BY distance", (vector[0].tobytes(), limit)
                )
            ]

    def search(self, query: str, limit: int = 4) -> str:
        scores: dict[int, float] = {}
        for weight, ranking in ((VECTOR_WEIGHT, self._vector_ids(query, 20)), (KEYWORD_WEIGHT, self._keyword_ids(query, 20))):
            for position, rowid in enumerate(ranking):
                scores[rowid] = scores.get(rowid, 0.0) + weight / (RRF_K + position + 1)
        if not scores:
            return "Nothing in the library about this"
        best = sorted(scores, key=scores.get, reverse=True)[:limit]
        with self.lock:
            rows = {
                rowid: (title, source, text)
                for rowid, title, source, text in self.db.execute(
                    f"SELECT p.rowid, s.title, s.source, p.text FROM passages p JOIN sources s ON s.id = p.source_id WHERE p.rowid IN ({','.join('?' * len(best))})",
                    best,
                )
            }
        return "\n\n".join(f"[{rows[r][0]} - {rows[r][1]}]\n{rows[r][2]}" for r in best if r in rows)

    def sources(self) -> list[tuple[str, str, int]]:
        with self.lock:
            return self.db.execute(
                "SELECT s.title, s.source, (SELECT count(*) FROM passages p WHERE p.source_id = s.id) FROM sources s ORDER BY s.learned_at DESC"
            ).fetchall()

    def forget(self, source: str) -> bool:
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM sources WHERE source = ? OR title = ?", (source, source)).fetchone()
            if not row:
                return False
            self._delete_passages(row[0])
            self.db.execute("DELETE FROM sources WHERE id = ?", (row[0],))
            return True
