import json
from datetime import datetime, timezone

from iris.dataset.jsonl import JsonlDatasetRecorder
from iris.domain.models import Interaction, Message, Role


def test_writes_one_json_line_per_interaction(tmp_path):
    path = tmp_path / "data" / "interactions.jsonl"
    recorder = JsonlDatasetRecorder(path)
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    interaction = Interaction("hi", [], [Message(Role.USER, "hi")], "hello", "fake", now, now)

    recorder.record(interaction)
    recorder.record(interaction)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["answer"] == "hello"
    assert entry["messages"][0]["role"] == "user"
    assert entry["started_at"] == "2026-10-08T00:00:00+00:00"


def test_sqlite_recorder_rates_and_exports_good_answers(tmp_path):
    from iris.dataset.sqlite import SQLiteDatasetRecorder

    recorder = SQLiteDatasetRecorder(tmp_path / "iris.db")
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    recorder.record(Interaction("oi", [], [Message(Role.USER, "oi")], "Olá!", "fake", now, now))
    recorder.record(Interaction("tchau", [], [Message(Role.USER, "tchau")], "Até!", "fake", now.replace(hour=1), now))
    recorder.rate_last("negative", correction="Até mais, Gabriel!")

    out = tmp_path / "train.jsonl"
    assert recorder.export_chat(out, "system") == 1
    example = json.loads(out.read_text(encoding="utf-8"))
    assert example["messages"][2]["content"] == "Até mais, Gabriel!"
    assert recorder.export_chat(out, "system", include_unrated=True) == 2
