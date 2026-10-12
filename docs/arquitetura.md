# Arquitetura da Iris

Registro das decisões de arquitetura. Atualize este arquivo quando uma decisão mudar.

## Objetivo

Assistente pessoal de voz e de terminal para Windows. Conversa em português, aprende com o uso (memória), age no computador por ferramentas e grava cada conversa para treinar um modelo próprio (iris-1), que pode substituir o Claude nas tarefas do dia a dia.

## Camadas (hexagonal / ports & adapters)

| Camada | Pasta | Responsabilidade | Pode depender de |
|---|---|---|---|
| Interface | `ui/`, `cli.py`, `frontend/` | Janela de voz (pywebview + Qt + React) e linha de comando | application, domain |
| Composição | `composition.py`, `app.py` | Monta ferramentas, memória e modelo para cada perfil (desktop ou CLI) | todas |
| Aplicação | `application/` | Conversa, intenção, correção fuzzy de nomes, filtro de conteúdo, roteador rápido | agent, domain |
| Agente | `agent/` | Loop LLM ↔ tools, guardrails, prompts, ports, tools | domain |
| Domínio | `domain/` | Modelos e regras puras | nada |
| Conhecimento | `knowledge/` | Memória em SQLite com busca FTS5 | agent (ports), domain |
| Dataset | `dataset/` | Gravação das conversas e avaliações para treino | agent (ports), domain |
| Infraestrutura | `infrastructure/` | Adapters: Claude (API e Agent SDK), Ollama, Jev, voz (Whisper, edge-tts), Windows (apps, teclado, tela, arquivos) | agent (ports), domain |

Regra: dependências apontam para dentro. O núcleo (`agent/`, `application/` e `domain/`) não importa UI nem SDKs de terceiros. A montagem acontece só em `composition.py`.

## Padrões adotados

- **Ports & Adapters**: `agent/ports.py` define `LLMProvider`, `Tool`, `KnowledgeBase`, `DatasetRecorder` e `Approver`.
- **Tool pattern**: cada ação é uma classe `Tool` com `name`, `description`, `input_schema`, `access` e `run()`, agrupadas por assunto em `agent/tools/`. Toda tool nova é registrada em `composition.py` e citada em `agent/prompts/system.md`.
- **Guardrails**: o filtro de conteúdo vale para pedidos, chamadas de tool e respostas. Ações irreversíveis (apagar arquivos, comandos que alteram algo, aplicar mudança no próprio código) exigem confirmação do usuário numa fala seguinte, verificada no código.
- **Strategy de modelo**: o loop só conhece `LLMProvider`. `ClaudeProvider` (API, com pesquisa na web), `ClaudeAgentEngine` (Agent SDK) e `OllamaProvider` (iris-1 local).
- **Perfis**: `desktop` (voz, janela, todas as tools) e `cli` (texto, respostas mais longas, sem tools de janela).
- **Configuração tipada**: `config.py` com pydantic-settings (prefixo `IRIS_`), lida do ambiente e de `%LOCALAPPDATA%\iris\settings.env`. Chaves de API no Windows Credential Manager via keyring, nunca em arquivo.

## Decisões

| Decisão | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.12 + React | Ecossistema de IA no back, interface moderna no front |
| Janela | pywebview com Qt (PySide6), transparente | WebView2/WinForms não recorta nem fica transparente (DirectComposition) |
| Fala para texto | Whisper `base` (faster-whisper) local + correção fuzzy fonética | Bom em português, offline, ~1 s por frase na CPU |
| Texto para fala | edge-tts (voz neural pt-BR Francisca), SAPI como reserva | Voz natural sem custo |
| Modelo | Claude Haiku pela API (padrão), Agent SDK ou iris-1 no Ollama | Rápido e barato; modelo próprio para uso offline |
| Dataset | SQLite com avaliações e correções | Exporta direto para fine-tuning |
| Fine-tuning | Qwen3-4B com LoRA (Unsloth) no Google Colab, exportado em GGUF | Cabe em GPU gratuita e roda local no Ollama |

## Convenções

- Código sempre em inglês: módulos, classes, funções, variáveis e testes. Documentação e textos para o usuário em português.
- Sem comentários no código; nomes claros fazem esse papel.

## Testes

`pytest` com adapters falsos (`tests/fakes.py`). O núcleo é testado sem rede e sem UI.
