# Treino do modelo da Iris

O modelo próprio da Iris, o **iris-1**, é um **Qwen3.5** (9B, 4B ou 2B, conforme a placa de quem usa) ajustado com
**LoRA** em cima de conversas no estilo dela. Quem baixa o iris-1 roda o modelo na própria placa de vídeo.
O Claude continua sendo o "professor": gera os exemplos e segue cuidando das tarefas pesadas (código, visão de tela).

## 1. Gerar os dados (no notebook)

```powershell
cd C:\projetos\iris
.venv\Scripts\python.exe scripts\training\generate_dataset.py --out "$env:LOCALAPPDATA\iris\dataset\synthetic.jsonl"
```

- Cria cerca de 500 cenários por categoria (abrir apps, YouTube, arquivos, comandos, conversa, áudio que não é com ela etc.).
- Roda cada um pela mesma lógica da Iris (mesmo prompt e mesmas ferramentas, com ações simuladas), usando o Claude Sonnet 5.5.
- Um juiz (Claude Haiku 5.5) descarta conversas que inventam fatos, quebram as regras de confirmação ou fogem do estilo de voz.
- Custo aproximado: US$ 4 a 6 por rodada completa.

O gerador tem dois conjuntos: `--set base` (ferramentas e voz) e `--set extra` (todos os outros assuntos, por voz e por
terminal, com um juiz Sonnet mais rigoroso que reprova código ou fato errado). Para juntar os arquivos num só para o treino:

```powershell
.venv\Scripts\python.exe scripts\training\merge_datasets.py synthetic.jsonl synthetic-extra.jsonl --out synthetic-all.jsonl
```

As conversas reais avaliadas por voz ("essa resposta foi boa", "o certo é...") podem ser exportadas com
`python -m iris.dataset.export` e somadas ao treino quando houver volume.

## 2. Treinar (GPU alugada ou Colab)

O Qwen3.5 treina em 16 bits (o Unsloth não recomenda 4 bits nele). O 9B precisa de uns 30 GB de memória de vídeo,
o 4B de uns 18 GB e o 2B de uns 12 GB, então o treino roda numa GPU alugada, uma vez por tamanho.
O notebook [notebooks/train_iris_colab.ipynb](../notebooks/train_iris_colab.ipynb) funciona nos dois lugares:

- **RunPod, A100 80 GB (recomendado):** cerca de 1 hora e uns US$ 2 por tamanho. Crie um pod com o template PyTorch, envie o notebook e o
  `synthetic.jsonl` para `/workspace/iris-1/`, rode tudo, baixe `/workspace/iris-1/gguf` e desligue o pod.
- **Google Colab:** A100 do Colab Pro para o 9B; a T4 grátis só aguenta o 2B. O resultado vai para o Drive em `iris-1/`.

Também dá pra rodar o mesmo treino por linha de comando em qualquer Linux com GPU:

```bash
pip install -r scripts/training/requirements.txt
python scripts/training/train_lora.py synthetic.jsonl --out iris-model          # --model 4b ou 2b para as versões menores
```

- Cada exemplo tem uns 4.000 a 5.000 tokens (as ferramentas sozinhas somam ~2.800), então o limite padrão é 5.120.
- No fim aparecem o adaptador LoRA em `lora/` e o modelo pronto pro Ollama em `gguf/` (arquivo `.gguf` + `Modelfile`), com uns 5 GB.

## 3. Carregar no Ollama

Instale o Ollama (`winget install Ollama.Ollama`) na máquina que vai rodar o modelo e, na pasta `iris-model/gguf`:

```powershell
ollama create iris-1 -f Modelfile
ollama run iris-1 "abre o chrome"
```

Se o `Modelfile` gerado não tiver `TEMPLATE`, copie o do modelo base: `ollama show qwen3.5:9b --modelfile`.

Onde rodar:
- **Na própria máquina da 3060 (recomendado):** resposta rápida. A Iris do notebook acessa pela rede com `IRIS_OLLAMA_HOST=http://IP-DA-MAQUINA:11434`. No Windows da 3060, defina `OLLAMA_HOST=0.0.0.0` para aceitar conexões.
- **Sem placa de vídeo:** o 9B no processador fica lento demais pra voz; use o iris-1 2B.

## 4. Ligar a Iris no modelo próprio

No arquivo `C:\projetos\iris\.env`:

```
IRIS_LLM_BACKEND=local
IRIS_LOCAL_MODEL=iris
IRIS_OLLAMA_HOST=http://127.0.0.1:11434
```

Reinicie a Iris. Para voltar ao Claude, troque para `IRIS_LLM_BACKEND=auto`.
A visão da tela e as mudanças no próprio código continuam usando o Claude.
