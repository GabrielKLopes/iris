import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from iris.domain.models import Fact

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "um", "uma", "meu", "minha",
    "qual", "que", "e", "eh", "pra", "para", "me", "ve", "ver", "sobre", "com", "por", "se", "voce", "isso",
}


def _terms(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 1 and w not in STOPWORDS]


class SQLiteMemory:
    def __init__(self, path: Path, always_include_up_to: int = 40):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.always_include_up_to = always_include_up_to
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(content, content='facts', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, content) VALUES ('delete', old.id, old.content);
            END;
            """
        )

    def remember(self, content: str) -> Fact:
        created_at = datetime.now(timezone.utc)
        cursor = self.db.execute(
            "INSERT INTO facts (content, created_at) VALUES (?, ?)", (content.strip(), created_at.isoformat())
        )
        self.db.commit()
        return Fact(cursor.lastrowid, content.strip(), created_at)

    def forget(self, fact_id: int) -> bool:
        cursor = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.db.commit()
        return cursor.rowcount > 0

    def all(self) -> list[Fact]:
        rows = self.db.execute("SELECT id, content, created_at FROM facts ORDER BY id").fetchall()
        return [Fact(r[0], r[1], datetime.fromisoformat(r[2])) for r in rows]

    def search(self, query: str, limit: int = 5) -> list[str]:
        facts = self.all()
        if len(facts) <= self.always_include_up_to:
            return [self._format(f) for f in facts]
        terms = _terms(query)
        if not terms:
            return [self._format(f) for f in facts[-limit:]]
        match = " OR ".join(f'"{t}"*' for t in terms)
        rows = self.db.execute(
            "SELECT f.id, f.content, f.created_at FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
            "WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
        return [self._format(Fact(r[0], r[1], datetime.fromisoformat(r[2]))) for r in rows]

    @staticmethod
    def _format(fact: Fact) -> str:
        return f"[#{fact.id}] {fact.content}"
