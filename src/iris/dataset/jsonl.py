import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from iris.domain.models import Interaction


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Not serializable: {type(value).__name__}")


class JsonlDatasetRecorder:
    def __init__(self, path: Path):
        self.path = path

    def record(self, interaction: Interaction) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(interaction), ensure_ascii=False, default=_serialize)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
