import logging
import sys
import threading
from importlib import resources
from pathlib import Path

from iris.agent.guardrails import Guardrail
from iris.agent.ports import Approver
from iris.agent.tools import ToolRegistry
from iris.agent.tools.memory import ForgetTool, RememberTool
from iris.agent.tools.weather import WeatherTool
from iris.config import Settings
from iris.dataset.sqlite import SQLiteDatasetRecorder
from iris.knowledge.sqlite_memory import SQLiteMemory

REPO = Path(__file__).resolve().parents[2]
DESKTOP = "desktop"
CLI = "cli"


def system_prompt(settings: Settings, profile: str = DESKTOP) -> str:
    prompts = resources.files("iris.agent").joinpath("prompts")
    text = prompts.joinpath("system.md").read_text(encoding="utf-8").replace("{user}", settings.user_name or "the user")
    if profile == CLI:
        text += "\n" + prompts.joinpath("cli.md").read_text(encoding="utf-8")
    from iris.i18n import ANSWER_LANGUAGE, normalize

    return text.replace("{language}", ANSWER_LANGUAGE[normalize(settings.language)])


def announce(job) -> str:
    if job.status == "ready":
        return f"Terminei a mudança no meu código. {job.summary} Os testes passaram. Quer que eu aplique e reinicie?"
    if job.status == "tests_failed":
        return f"Terminei a mudança, mas os testes falharam, então não vou aplicar. {job.summary}"
    if job.status == "no_changes":
        return f"Analisei o pedido, mas não precisei mudar nenhum arquivo. {job.summary}"
    return "A mudança no meu código deu erro e não foi concluída."


def code_worker(window):
    from iris.infrastructure.coding.claude_code_worker import ClaudeCodeWorker

    python = Path(sys.executable).with_name("python.exe")
    return ClaudeCodeWorker(REPO, python, on_finished=lambda job: window and window.notify(announce(job)))


def screen_tools(settings: Settings, *tool_classes):
    from iris.infrastructure.secrets import ANTHROPIC_KEY, get_secret

    api_key = get_secret(ANTHROPIC_KEY)
    if not api_key:
        return []
    from iris.infrastructure.windows.screen import ScreenVision

    vision = ScreenVision(api_key, settings.api_model)
    return [tool_class(vision) for tool_class in tool_classes]


def web_search_for(settings: Settings):
    from iris.infrastructure.secrets import BRAVE_KEY, TAVILY_KEY, get_secret
    from iris.infrastructure.web.search import WebSearch, providers_from

    providers = providers_from(settings, get_secret, TAVILY_KEY, BRAVE_KEY)
    logging.info("Web search providers: %s", ", ".join(p.name for p in providers))
    return WebSearch(providers)


def library_for(settings: Settings, index_in_background: bool = True):
    from iris.infrastructure.windows.browser import current_browser_url
    from iris.infrastructure.windows.files import LocalFiles
    from iris.knowledge.embeddings import FastEmbedder
    from iris.knowledge.library import SQLiteLibrary

    embedder = FastEmbedder(settings.embedding_cache) if settings.library_vectors else None
    library = SQLiteLibrary(settings.library_db, LocalFiles().resolve, current_browser_url, embedder)
    if index_in_background and library.vectors:
        threading.Thread(target=library.index_missing, daemon=True).start()
    return library


def build_tools(
    settings: Settings, memory: SQLiteMemory, window, recorder: SQLiteDatasetRecorder, profile: str = DESKTOP, web_search: bool = True,
) -> ToolRegistry:
    from iris.agent.tools.coding import AnalyzeOwnCodeTool, ApplyCodeChangeTool, CodeChangesStatusTool, StartCodeChangeTool
    from iris.agent.tools.commands import RunCommandTool
    from iris.agent.tools.desktop import (
        ClickOnScreenTool,
        CloseAppTool,
        CloseTabTool,
        ExitTool,
        LookAtScreenTool,
        MediaControlTool,
        MoveWindowTool,
        OpenAppTool,
        OpenUrlTool,
        YoutubeTool,
    )
    from iris.agent.tools.feedback import RateAnswerTool
    from iris.agent.tools.knowledge import LearnUrlTool, SearchLibraryTool, WebSearchTool
    from iris.agent.tools.files import (
        CreateFolderTool,
        DeleteFilesTool,
        FindFilesTool,
        ListFolderTool,
        MoveFilesTool,
        OpenPathTool,
        ReadFileTool,
        WriteFileTool,
    )
    from iris.infrastructure.weather.open_meteo import OpenMeteoWeather
    from iris.infrastructure.windows.apps import WindowsAppLauncher
    from iris.infrastructure.windows.files import LocalFiles
    from iris.infrastructure.windows.keyboard import WindowsDesktopKeys

    launcher = WindowsAppLauncher()
    files = LocalFiles()
    keys = WindowsDesktopKeys()
    turn = lambda: getattr(window, "turn", 0)  # noqa: E731
    threading.Thread(target=launcher.apps, daemon=True).start()
    library = library_for(settings)
    tools = [
        RememberTool(memory),
        ForgetTool(memory),
        WeatherTool(OpenMeteoWeather()),
        OpenAppTool(launcher),
        CloseAppTool(launcher),
        CloseTabTool(keys),
        *screen_tools(settings, LookAtScreenTool, ClickOnScreenTool),
        MediaControlTool(keys),
        OpenUrlTool(launcher),
        YoutubeTool(launcher),
        RateAnswerTool(recorder),
        ListFolderTool(files),
        FindFilesTool(files),
        CreateFolderTool(files),
        MoveFilesTool(files),
        OpenPathTool(files),
        ReadFileTool(files),
        WriteFileTool(files),
        DeleteFilesTool(files, turn),
        RunCommandTool(turn),
        SearchLibraryTool(library),
        LearnUrlTool(library),
    ]
    if web_search:
        tools.append(WebSearchTool(web_search_for(settings)))
    if (REPO / ".git").exists():
        worker = code_worker(window)
        tools += [
            AnalyzeOwnCodeTool(worker),
            StartCodeChangeTool(worker),
            CodeChangesStatusTool(worker),
            ApplyCodeChangeTool(worker, turn, lambda: window.request_restart()),
        ]
    if profile == DESKTOP:
        tools += [MoveWindowTool(window), ExitTool(window)]
    return ToolRegistry(tools)


def recorder_for(settings: Settings) -> SQLiteDatasetRecorder:
    recorder = SQLiteDatasetRecorder(settings.dataset_db)
    imported = recorder.import_jsonl(settings.dataset_file)
    if imported:
        logging.info("Imported %d conversations from JSONL", imported)
    return recorder


def _claude_code_engine(settings: Settings, approver: Approver, window, profile: str):
    from iris.infrastructure.llm.claude_agent import ClaudeAgentEngine

    memory = SQLiteMemory(settings.memory_file)
    recorder = recorder_for(settings)
    return ClaudeAgentEngine(
        tools=build_tools(settings, memory, window, recorder, profile),
        guardrail=Guardrail(approver),
        knowledge=memory,
        recorder=recorder,
        system_prompt=system_prompt(settings, profile),
        model=settings.llm_model,
        max_turns=settings.max_steps,
        cwd=settings.agent_workdir,
    )


def ledger_for(settings: Settings):
    import getpass

    from iris.dataset.usage_ledger import SQLiteUsageLedger

    return SQLiteUsageLedger(settings.usage_db, settings.user_name or getpass.getuser())


def _loop_engine(settings: Settings, approver: Approver, window, profile: str, llm, web_search: bool = True):
    from iris.agent.loop import AgentLoop
    from iris.application.conversation import Conversation

    memory = SQLiteMemory(settings.memory_file)
    recorder = recorder_for(settings)
    loop = AgentLoop(
        llm=llm,
        tools=build_tools(settings, memory, window, recorder, profile, web_search),
        guardrail=Guardrail(approver),
        knowledge=memory,
        recorder=recorder,
        system_prompt=system_prompt(settings, profile),
        max_steps=settings.max_steps,
        ledger=ledger_for(settings),
    )
    return Conversation(loop)


def _anthropic_api_engine(settings: Settings, approver: Approver, window, profile: str):
    from iris.infrastructure.llm.claude import WEB_SEARCH, ClaudeProvider
    from iris.infrastructure.secrets import ANTHROPIC_KEY, get_secret

    api_key = get_secret(ANTHROPIC_KEY)
    if not api_key:
        raise RuntimeError("Chave da API da Anthropic não encontrada. Rode `iris setup` para configurar.")
    max_tokens = 4096 if profile == CLI else 1024
    llm = ClaudeProvider(api_key, settings.api_model, max_tokens=max_tokens, server_tools=[WEB_SEARCH])
    return _loop_engine(settings, approver, window, profile, llm, web_search=False)


def _local_engine(settings: Settings, approver: Approver, window, profile: str):
    from iris.infrastructure.llm.ollama import OllamaProvider

    return _loop_engine(settings, approver, window, profile, OllamaProvider(settings.local_model, settings.ollama_host))


def uses_api(backend: str) -> bool:
    if backend != "auto":
        return backend == "anthropic_api"
    from iris.infrastructure.secrets import ANTHROPIC_KEY, get_secret

    return bool(get_secret(ANTHROPIC_KEY))


def build_engine(settings: Settings, approver: Approver, window=None, profile: str = DESKTOP):
    if settings.llm_backend == "local":
        builder = _local_engine
    elif settings.llm_backend == "claude_code" or not uses_api(settings.llm_backend):
        builder = _claude_code_engine
    else:
        builder = _anthropic_api_engine
    logging.info("LLM backend: %s (%s)", builder.__name__, profile)
    return builder(settings, approver, window, profile)


def router_for(window):
    from iris.infrastructure.secrets import TYPESAFE_KEY, get_secret

    api_key = get_secret(TYPESAFE_KEY)
    if not api_key:
        logging.info("Fast router disabled: no TypeSafe key")
        return None
    from iris.application.router import FastRouter
    from iris.infrastructure.llm.typesafe import JevClient
    from iris.infrastructure.windows.apps import WindowsAppLauncher
    from iris.infrastructure.windows.keyboard import WindowsDesktopKeys

    launcher, keys = WindowsAppLauncher(), WindowsDesktopKeys()
    threading.Thread(target=launcher.apps, daemon=True).start()
    actions = {
        "open_app": launcher.launch,
        "close_app": launcher.close,
        "close_tab": lambda: keys.close_tab(),
        "play_pause": lambda: keys.media("play_pause"),
        "next": lambda: keys.media("next"),
        "volume_up": lambda: keys.media("volume_up"),
        "volume_down": lambda: keys.media("volume_down"),
        "hide": lambda: window.request_exit("hide"),
    }
    logging.info("Fast router enabled (Jev)")
    return FastRouter(JevClient(api_key), launcher.common, actions)


def corrector_for(settings: Settings):
    from iris.application.fuzzy import TranscriptCorrector, default_vocabulary

    memory = SQLiteMemory(settings.memory_file)
    return TranscriptCorrector(default_vocabulary(lambda: [fact.content for fact in memory.all()]))
