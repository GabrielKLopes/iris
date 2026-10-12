<p align="center"><img src="assets/iris.png" width="140" alt="Iris"></p>

# Iris

Assistente pessoal de voz e de terminal para Windows, em português. Você chama "Iris" e conversa: ela abre programas, toca vídeos no YouTube, mexe nas suas pastas, roda comandos, pesquisa na web, olha a tela e aprende com o uso.

- **Desktop:** uma esfera flutuante que ouve seu chamado ("Iris", "boa noite, Iris") e responde por voz.
- **CLI:** o comando `iris` no terminal, para perguntas rápidas, pesquisa e conversa por texto.

## Instalação

Baixe a versão desktop ou a CLI na [página de releases](../../releases) e, na primeira vez, configure:

```powershell
iris setup
```

O setup pergunta seu nome e a chave da API da Anthropic (crie em [console.anthropic.com](https://console.anthropic.com)). A chave fica no Gerenciador de Credenciais do Windows, nunca em arquivo.

## Uso no terminal

```powershell
iris                       # abre o terminal da Iris (conversa, ferramentas e confirmações na tela)
iris "qual a previsão do tempo amanhã em Curitiba?"
iris memory list
iris library learn https://docs.docker.com/compose/
iris desktop
```

No terminal da Iris, `/ajuda` mostra os comandos (`/nova`, `/memoria`, `/biblioteca`, `/aprender`). Use `iris chat --simples` para a conversa em texto puro.

## O que ela faz

| Área | Exemplos |
|---|---|
| Programas e janelas | "abre o VS Code", "fecha a aba do YouTube", "vai pro monitor 2" |
| YouTube e mídia | "toca Coldplay", "abre o canal do Fabio Akita", "pausa" |
| Pesquisa | "qual a cotação do dólar hoje?", "o que saiu de novo no Python 3.14?" |
| Arquivos | "o que tem nos meus downloads?", "apaga os instaladores antigos" (sempre pergunta antes) |
| Terminal | "qual a branch desse repositório?", "lista os containers" (comandos que alteram algo pedem confirmação) |
| Tela | "o que tá aparecendo na minha tela?", "clica no segundo vídeo" |
| Memória | "lembra que meu time joga quinta" e ela usa isso depois |

Pedidos com conteúdo sexual, racismo ou ódio são recusados.

## Desenvolvimento

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python.exe -m iris        # desktop
.\.venv\Scripts\iris.exe chat             # CLI
.\.venv\Scripts\python.exe -m pytest      # testes
```

A arquitetura e as decisões estão em [docs/arquitetura.md](docs/arquitetura.md).

## Modelo próprio (iris-1)

Toda conversa fica gravada localmente e pode virar exemplo de treino. O notebook [notebooks/train_iris_colab.ipynb](notebooks/train_iris_colab.ipynb) treina o **iris-1** (Qwen3.5 com LoRA, em 9B, 4B ou 2B) no Google Colab ou numa GPU alugada (RunPod, uns US$ 2), e o resultado roda local no [Ollama](https://ollama.com) com `IRIS_LLM_BACKEND=local`, usando a placa de vídeo de quem roda. Detalhes em [docs/treino.md](docs/treino.md).

## Licença

[MIT](LICENSE)
