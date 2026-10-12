import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "notebooks" / "train_iris_colab.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.strip().splitlines(keepends=True)}


CELLS = [
    md("""
# Treino do iris-1

Ajusta o **Qwen3.5** com LoRA nas conversas da Iris e exporta o modelo **iris-1** pronto para o Ollama.

| Tamanho | Para quem vai rodar | GPU para treinar | Tempo |
|---|---|---|---|
| `9b` | placa com 8 GB ou mais | A100 (40 ou 80 GB) | ~1 h |
| `4b` | placa com 4 a 6 GB | L4, A100 | ~40 min |
| `2b` | sem placa de vídeo | T4 grátis, L4, A100 | ~30 min |

**RunPod (recomendado, A100 80 GB, ~US$ 1,5/h)**
1. Crie um pod com o template **PyTorch** e GPU **A100 80 GB**, abra o **Jupyter Lab**.
2. Envie este notebook e o `iris-1-dados.jsonl` para `/workspace/iris-1/`, escolha o `SIZE` e rode tudo.
3. Baixe a pasta `/workspace/iris-1/gguf-<tamanho>` e **desligue o pod** (a cobrança é por hora ligada).

**Google Colab**
1. Em **Ambiente de execução > Alterar o tipo de ambiente**, escolha **A100** (Colab Pro) ou **T4** para o `2b`.
2. Rode tudo e, quando pedir, envie o `iris-1-dados.jsonl`. O resultado fica no Drive em `iris-1/`.
"""),
    code("""
SIZE = "9b"  # 9b, 4b ou 2b
"""),
    code("""
import importlib.util
IN_COLAB = importlib.util.find_spec("google.colab") is not None
!pip install -q unsloth trl datasets
if IN_COLAB:
    !pip install -q "transformers>=5"

import torch
gpu = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
print("GPU:", f"{gpu.name} ({gpu.total_memory / 1024**3:.0f} GB)" if gpu else "nenhuma (escolha um ambiente com GPU)")
NEEDED = {"9b": 30, "4b": 18, "2b": 12}[SIZE]
if gpu and gpu.total_memory / 1024**3 < NEEDED:
    print(f"Atenção: o {SIZE} precisa de uns {NEEDED} GB para treinar. Escolha uma GPU maior ou um SIZE menor.")
"""),
    md("## 1. Dados de treino"),
    code("""
import os

if IN_COLAB:
    from google.colab import drive, files
    drive.mount("/content/drive")
    OUT = "/content/drive/MyDrive/iris-1"
else:
    OUT = "/workspace/iris-1"

DATA = f"{OUT}/iris-1-dados.jsonl"
os.makedirs(OUT, exist_ok=True)
if not os.path.exists(DATA):
    if not IN_COLAB:
        raise SystemExit(f"Envie o iris-1-dados.jsonl para {DATA} pelo Jupyter Lab e rode de novo")
    print("Envie o iris-1-dados.jsonl:")
    uploaded = files.upload()
    with open(DATA, "wb") as f:
        f.write(next(iter(uploaded.values())))
print("Dados em", DATA)
"""),
    md("## 2. Modelo base e LoRA"),
    code("""
from unsloth import FastLanguageModel, is_bf16_supported

BASE_MODEL = f"unsloth/Qwen3.5-{SIZE.upper()}"
MAX_SEQ = 12288
BIG_GPU = gpu.total_memory > 60 * 1024**3

model, tokenizer = FastLanguageModel.from_pretrained(
    BASE_MODEL, max_seq_length=MAX_SEQ, load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
)
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth",
    max_seq_length=MAX_SEQ,
    random_state=7,
)
"""),
    code("""
import json
from datasets import Dataset

examples = [json.loads(line) for line in open(DATA, encoding="utf-8") if line.strip()]
texts = [
    {"text": tokenizer.apply_chat_template(e["messages"], tools=e.get("tools"), tokenize=False, enable_thinking=False)}
    for e in examples
]
text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
texts = [t for t in texts if len(text_tokenizer(text=t["text"]).input_ids) <= MAX_SEQ]
split = Dataset.from_list(texts).shuffle(seed=7).train_test_split(test_size=0.05, seed=7)
print(len(split["train"]), "exemplos de treino,", len(split["test"]), "de avaliacao")
"""),
    md("## 3. Treino"),
    code("""
from trl import SFTConfig, SFTTrainer
from unsloth.chat_templates import train_on_responses_only

CHECKPOINTS = f"{OUT}/checkpoints-{SIZE}"

trainer = SFTTrainer(
    model=model,
    tokenizer=text_tokenizer,
    train_dataset=split["train"],
    eval_dataset=split["test"],
    args=SFTConfig(
        dataset_text_field="text",
        max_seq_length=MAX_SEQ,
        per_device_train_batch_size=2 if BIG_GPU else 1,
        gradient_accumulation_steps=4 if BIG_GPU else 8,
        num_train_epochs=2,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="steps",
        save_steps=25,
        save_total_limit=2,
        optim="adamw_8bit",
        bf16=is_bf16_supported(),
        fp16=not is_bf16_supported(),
        output_dir=CHECKPOINTS,
        report_to="none",
    ),
)
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\\n", response_part="<|im_start|>assistant\\n")
resume = os.path.isdir(CHECKPOINTS) and any(name.startswith("checkpoint-") for name in os.listdir(CHECKPOINTS))
print("Continuando de onde parou" if resume else "Começando o treino")
trainer.train(resume_from_checkpoint=resume or None)
"""),
    md("## 4. Teste rápido"),
    code("""
FastLanguageModel.for_inference(model)
for question in ["abre o chrome pra mim", "qual a cotação do dólar hoje?", "me ajuda a criar um docker-compose com postgres e redis"]:
    messages = [{"role": "system", "content": examples[0]["messages"][0]["content"]}, {"role": "user", "content": question}]
    prompt = tokenizer.apply_chat_template(
        messages, tools=examples[0].get("tools"), add_generation_prompt=True, enable_thinking=False, tokenize=False,
    )
    inputs = text_tokenizer(text=prompt, return_tensors="pt").to("cuda")
    answer = model.generate(**inputs, max_new_tokens=400)[0][inputs["input_ids"].shape[1]:]
    print(f"--- {question}\\n{text_tokenizer.decode(answer, skip_special_tokens=False)}\\n")
"""),
    md("## 5. Exportar o iris-1 para o Ollama"),
    code("""
model.save_pretrained(f"{OUT}/lora-{SIZE}")
text_tokenizer.save_pretrained(f"{OUT}/lora-{SIZE}")
model.save_pretrained_gguf(f"{OUT}/gguf-{SIZE}", text_tokenizer, quantization_method="q4_k_m")
print("Pronto. Arquivos em", OUT)
print(f"No seu PC: baixe a pasta gguf-{SIZE} e siga docs/treino.md para carregar no Ollama.")
"""),
]


def main() -> None:
    notebook = {
        "cells": CELLS,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "A100", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Notebook written to {OUT}")


if __name__ == "__main__":
    main()
