import argparse
from importlib import resources
from pathlib import Path

from iris.config import Settings
from iris.dataset.sqlite import SQLiteDatasetRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Iris conversations as a chat fine-tuning dataset")
    parser.add_argument("--out", type=Path, default=Path("dataset/train.jsonl"))
    parser.add_argument("--include-unrated", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    recorder = SQLiteDatasetRecorder(settings.dataset_db)
    recorder.import_jsonl(settings.dataset_file)
    system = resources.files("iris.agent").joinpath("prompts/system.md").read_text(encoding="utf-8")
    total = recorder.export_chat(args.out, system, include_unrated=args.include_unrated)
    print(f"{total} examples written to {args.out} ({recorder.count()} conversations recorded)")


if __name__ == "__main__":
    main()
