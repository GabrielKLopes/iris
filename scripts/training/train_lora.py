import argparse
import json
from pathlib import Path

from datasets import Dataset
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel, is_bf16_supported
from unsloth.chat_templates import train_on_responses_only

MODELS = {
    "9b": "unsloth/Qwen3.5-9B",
    "4b": "unsloth/Qwen3.5-4B",
    "2b": "unsloth/Qwen3.5-2B",
}


def load_examples(paths: list[Path]) -> list[dict]:
    examples = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                examples.append({"messages": entry["messages"], "tools": entry.get("tools")})
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune Iris with LoRA on a GPU (9b needs ~30 GB: RunPod or Colab A100)")
    parser.add_argument("datasets", nargs="+", type=Path, help="JSONL files produced by generate_dataset.py")
    parser.add_argument("--out", type=Path, default=Path("iris-model"))
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--model", choices=sorted(MODELS), default="9b", help="4b needs ~18 GB and 2b ~12 GB")
    parser.add_argument("--max-seq", type=int, default=12288)
    parser.add_argument("--quantization", default="q4_k_m")
    args = parser.parse_args()

    model, tokenizer = FastLanguageModel.from_pretrained(
        MODELS[args.model], max_seq_length=args.max_seq, load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=7,
    )

    examples = load_examples(args.datasets)
    texts = [{"text": tokenizer.apply_chat_template(e["messages"], tools=e["tools"], tokenize=False, enable_thinking=False)} for e in examples]
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    texts = [t for t in texts if len(text_tokenizer(text=t["text"]).input_ids) <= args.max_seq]
    dataset = Dataset.from_list(texts).shuffle(seed=7)
    split = dataset.train_test_split(test_size=0.05, seed=7)
    print(f"{len(split['train'])} training and {len(split['test'])} evaluation examples")

    trainer = SFTTrainer(
        model=model,
        tokenizer=text_tokenizer,
        train_dataset=split["train"],
        eval_dataset=split["test"],
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=args.max_seq,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            num_train_epochs=args.epochs,
            learning_rate=2e-4,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            logging_steps=5,
            eval_strategy="epoch",
            save_strategy="no",
            optim="adamw_8bit",
            bf16=is_bf16_supported(),
            fp16=not is_bf16_supported(),
            output_dir=str(args.out / "checkpoints"),
            report_to="none",
        ),
    )
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")
    trainer.train()

    model.save_pretrained(str(args.out / "lora"))
    text_tokenizer.save_pretrained(str(args.out / "lora"))
    model.save_pretrained_gguf(str(args.out / "gguf"), text_tokenizer, quantization_method=args.quantization)
    print(f"Done. GGUF model in {args.out / 'gguf'}; see docs/treino.md to load it in Ollama")


if __name__ == "__main__":
    main()
