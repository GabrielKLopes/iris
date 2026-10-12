import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from iris.agent.tools.files import ReadFileTool, WriteFileTool  # noqa: E402

OLD_SENTENCE = "Offer to tidy up when it helps, e.g. old installers in Downloads."


def schema(tool) -> dict:
    return {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}}


def new_files_sentence() -> str:
    text = (Path(__file__).resolve().parents[2] / "src/iris/agent/prompts/system.md").read_text(encoding="utf-8")
    start = text.index(OLD_SENTENCE)
    return text[start:text.index("\n", start)]


def upgrade(example: dict, sentence: str, extra_tools: list[dict]) -> dict:
    system = example["messages"][0]
    if OLD_SENTENCE in system["content"] and sentence not in system["content"]:
        system["content"] = system["content"].replace(OLD_SENTENCE, sentence, 1)
    names = {t["function"]["name"] for t in example["tools"]}
    for tool in extra_tools:
        if tool["function"]["name"] not in names:
            example["tools"].append(tool)
    return example


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge generated datasets into one shuffled training file")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    sentence = new_files_sentence()
    extra_tools = [schema(ReadFileTool(None)), schema(WriteFileTool(None))]
    examples = []
    for path in args.inputs:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        examples += [upgrade(row, sentence, extra_tools) for row in rows]
        print(f"{len(rows):5d} from {path.name}")
    random.Random(7).shuffle(examples)
    args.out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")
    print(f"{len(examples):5d} written to {args.out}")


if __name__ == "__main__":
    main()
