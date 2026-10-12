import argparse
import getpass
import logging
import subprocess
import sys
from pathlib import Path

from iris import __version__
from iris.application.content_policy import REFUSAL, ContentPolicy
from iris.config import Settings

COMMANDS = {"chat", "setup", "memory", "library", "desktop"}
DIM, CYAN, RESET = "\033[2m", "\033[36m", "\033[0m"


class TerminalApprover:
    def approve(self, call) -> bool:
        answer = input(f"\n{DIM}Iris quer executar {call.name} com {call.input}. Permitir? [s/N] {RESET}")
        return answer.strip().lower() in ("s", "sim", "y", "yes")


class TerminalSession:
    def __init__(self):
        self.turn = 0

    def notify(self, text: str) -> None:
        print(f"\n{CYAN}iris ›{RESET} {text}\n")

    def request_restart(self) -> None:
        print(f"{DIM}Mudança aplicada. Abra a Iris de novo para usar a versão nova.{RESET}")

    def request_exit(self, mode: str) -> None:
        return None


def _engine(settings: Settings, session: TerminalSession):
    from iris.composition import CLI, build_engine

    return build_engine(settings, TerminalApprover(), session, CLI)


def _answer(engine, session: TerminalSession, policy: ContentPolicy, question: str) -> None:
    session.turn += 1
    print(f"{CYAN}iris ›{RESET} ", end="", flush=True)
    if policy.check(question):
        print(REFUSAL)
        return
    printed: list[str] = []

    def stream(delta: str) -> None:
        printed.append(delta)
        print(delta, end="", flush=True)

    try:
        answer = engine.ask(question, on_text=stream)
    except Exception as exc:
        print(f"\nNão consegui responder: {exc}")
        return
    if not printed and answer:
        print(answer, end="")
    print("\n")


def chat(settings: Settings) -> None:
    session = TerminalSession()
    engine = _engine(settings, session)
    policy = ContentPolicy()
    name = settings.user_name or "você"
    print(f"Iris {__version__} · escreva sua pergunta. /nova limpa a conversa, /sair encerra.\n")
    while True:
        try:
            question = input(f"{name} › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            continue
        if question in ("/sair", "/exit", "/quit"):
            return
        if question == "/nova":
            engine.reset()
            print(f"{DIM}Conversa nova.{RESET}\n")
            continue
        try:
            _answer(engine, session, policy, question)
        except KeyboardInterrupt:
            print(f"\n{DIM}Interrompido.{RESET}\n")


def ask_once(settings: Settings, question: str) -> None:
    session = TerminalSession()
    _answer(_engine(settings, session), session, ContentPolicy(), question)


def setup(settings: Settings) -> None:
    from iris.infrastructure.secrets import ANTHROPIC_KEY, TAVILY_KEY, get_secret, set_secret

    print("Configuração da Iris\n")
    name = input(f"Como a Iris deve te chamar? [{settings.user_name or 'sem nome'}] ").strip() or settings.user_name
    if name:
        save_setting(settings.settings_file, "IRIS_USER_NAME", name)
    has_key = bool(get_secret(ANTHROPIC_KEY))
    key = getpass.getpass(
        "Chave da API da Anthropic (console.anthropic.com > API Keys)"
        + (" [Enter mantém a atual]: " if has_key else ": ")
    ).strip()
    if key:
        set_secret(ANTHROPIC_KEY, key)
    has_search = bool(get_secret(TAVILY_KEY))
    search_key = getpass.getpass(
        "Chave do Tavily para pesquisa na web, 1.000 buscas grátis por mês (tavily.com)"
        + (" [Enter mantém a atual]: " if has_search else " [Enter pula e usa o DuckDuckGo]: ")
    ).strip()
    if search_key:
        set_secret(TAVILY_KEY, search_key)
    print("\nPronto. Use `iris` para conversar ou `iris \"sua pergunta\"` para uma resposta rápida.")


def save_setting(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []) if not line.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def memory(settings: Settings, args: list[str]) -> None:
    from iris.knowledge.sqlite_memory import SQLiteMemory

    store = SQLiteMemory(settings.memory_file)
    action = args[0] if args else "list"
    if action == "list":
        facts = store.all()
        if not facts:
            print("A Iris ainda não sabe nada sobre você. Ensine com: iris memory add \"fato\"")
        for fact in facts:
            print(f"#{fact.id}  {fact.content}")
    elif action == "add" and len(args) > 1:
        fact = store.remember(" ".join(args[1:]))
        print(f"Guardado como #{fact.id}.")
    elif action == "forget" and len(args) > 1 and args[1].lstrip("#").isdigit():
        print("Esquecido." if store.forget(int(args[1].lstrip("#"))) else "Não encontrei esse fato.")
    else:
        print("Uso: iris memory [list | add \"fato\" | forget ID]")


def library(settings: Settings, args: list[str]) -> None:
    from iris.composition import library_for

    store = library_for(settings, index_in_background=False)
    action = args[0] if args else "list"
    if action == "list":
        sources = store.sources()
        if not sources:
            print("A biblioteca está vazia. Ensine com: iris library learn <link, arquivo ou pasta>")
        for title, source, count in sources:
            print(f"{title}\n   {source} ({count} trechos)")
    elif action == "learn" and len(args) > 1:
        print(store.learn(" ".join(args[1:])))
    elif action == "search" and len(args) > 1:
        print(store.search(" ".join(args[1:])))
    elif action == "forget" and len(args) > 1:
        print("Esquecido." if store.forget(" ".join(args[1:])) else "Não encontrei essa fonte. Veja os nomes com: iris library list")
    elif action == "reindex":
        print(f"{store.index_missing()} trechos indexados por significado.")
    else:
        print("Uso: iris library [list | learn <link, arquivo ou pasta> | search \"pergunta\" | forget <fonte> | reindex]")


def desktop() -> None:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    subprocess.Popen([str(executable), "-m", "iris"], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    print("Abrindo a Iris.")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="iris",
        description="Iris no terminal: converse, pesquise e peça coisas.",
        epilog="Exemplos: iris \"qual a previsão do tempo amanhã?\" · iris chat · iris memory list · iris setup",
    )
    parser.add_argument("words", nargs="*", help="pergunta para uma resposta rápida, ou um comando: chat, setup, memory, library, desktop")
    parser.add_argument("--version", action="version", version=f"iris {__version__}")
    parser.add_argument("--simples", action="store_true", help="conversa em texto simples, sem a interface")
    args = parser.parse_args()

    settings = Settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=settings.log_dir / "iris-cli.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    words = args.words
    command = words[0] if words and words[0] in COMMANDS else None
    if command == "setup":
        setup(settings)
    elif command == "memory":
        memory(settings, words[1:])
    elif command == "library":
        library(settings, words[1:])
    elif command == "desktop":
        desktop()
    elif command == "chat" or not words:
        if args.simples or not sys.stdin.isatty() or not sys.stdout.isatty():
            chat(settings)
        else:
            from iris.tui.app import run

            run(settings)
    else:
        ask_once(settings, " ".join(words))


if __name__ == "__main__":
    main()
