import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path

from iris.domain.models import Interaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    context TEXT NOT NULL,
    messages TEXT NOT NULL,
    model TEXT NOT NULL,
    rating TEXT,
    correction TEXT,
    UNIQUE (started_at, question)
)
"""


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Not serializable: {type(value).__name__}")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=_serialize)


class SQLiteDatasetRecorder:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(SCHEMA)
        self._lock = threading.Lock()

    def record(self, interaction: Interaction) -> None:
        data = asdict(interaction)
        self._insert(
            data["started_at"].isoformat(),
            data["finished_at"].isoformat(),
            data["question"],
            data["answer"],
            _json(data["context"]),
            _json(data["messages"]),
            data["model"],
            data["rating"].value if data["rating"] else None,
            data["correction"],
        )

    def _insert(self, *row) -> None:
        with self._lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO interactions "
                "(started_at, finished_at, question, answer, context, messages, model, rating, correction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def import_jsonl(self, path: Path) -> int:
        if not path.exists():
            return 0
        before = self.count()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            self._insert(
                entry["started_at"],
                entry["finished_at"],
                entry["question"],
                entry["answer"],
                _json(entry.get("context", [])),
                _json(entry.get("messages", [])),
                entry.get("model", ""),
                entry.get("rating"),
                entry.get("correction"),
            )
        return self.count() - before

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]

    def rate_last(self, rating: str, correction: str | None = None) -> str:
        with self._lock, self.db:
            row = self.db.execute("SELECT id, question FROM interactions ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return "There is no answer to rate yet"
            self.db.execute("UPDATE interactions SET rating = ?, correction = ? WHERE id = ?", (rating, correction, row[0]))
        return f"Rated the answer to '{row[1]}' as {rating}"

    def export_chat(self, path: Path, system_prompt: str, include_unrated: bool = False) -> int:
        condition = "rating = 'positive' OR correction IS NOT NULL"
        if include_unrated:
            condition += " OR rating IS NULL"
        rows = self.db.execute(
            f"SELECT question, COALESCE(correction, answer) FROM interactions WHERE {condition} ORDER BY id"
        ).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            for question, answer in rows:
                example = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ]
                }
                file.write(json.dumps(example, ensure_ascii=False) + "\n")
        return len(rows)
