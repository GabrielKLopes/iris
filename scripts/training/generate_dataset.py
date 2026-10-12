import argparse
import json
import random
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from iris.agent.guardrails import Guardrail  # noqa: E402
from iris.agent.loop import AgentLoop  # noqa: E402
from iris.agent.tools import ToolRegistry  # noqa: E402
from iris.agent.tools.coding import AnalyzeOwnCodeTool, ApplyCodeChangeTool, CodeChangesStatusTool, StartCodeChangeTool  # noqa: E402
from iris.agent.tools.commands import RunCommandTool  # noqa: E402
from iris.agent.tools.desktop import (  # noqa: E402
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
from iris.agent.tools.feedback import RateAnswerTool  # noqa: E402
from iris.agent.tools.knowledge import LearnUrlTool, SearchLibraryTool, WebSearchTool  # noqa: E402
from iris.agent.tools.files import (  # noqa: E402
    CreateFolderTool,
    DeleteFilesTool,
    FindFilesTool,
    ListFolderTool,
    MoveFilesTool,
    OpenPathTool,
    ReadFileTool,
    WriteFileTool,
)
from iris.agent.tools.communication import (  # noqa: E402
    CreateEventTool,
    ListChatsTool,
    ListEmailsTool,
    ListEventsTool,
    ReadChatTool,
    ReadEmailTool,
    SendChatMessageTool,
    SendEmailTool,
)
from iris.agent.tools.memory import ForgetTool, RememberTool  # noqa: E402
from iris.agent.tools.weather import WeatherTool  # noqa: E402
from iris.application.conversation import Conversation  # noqa: E402
from iris.application.intent import normalize  # noqa: E402
from iris.domain.models import Role  # noqa: E402
from iris.infrastructure.llm.claude import ClaudeProvider  # noqa: E402
from iris.infrastructure.secrets import ANTHROPIC_KEY, get_secret  # noqa: E402
from iris.knowledge.sqlite_memory import SQLiteMemory  # noqa: E402

TEACHER = "claude-sonnet-5-5"
JUDGE = "claude-haiku-5-5"
SLOW_TOOLS = {"analyze_own_code", "start_code_change"}
NAME = re.compile(r"(,\s*the user(?=[.!?,]))|(^the user,\s*)")

JUDGE_PROMPT = """You review a training conversation for Iris, a Brazilian Portuguese voice assistant. Tool results are simulated.
Fail it if the assistant: states something factually wrong; invents facts, numbers, IPs or names that neither the user nor a tool result gave;
reads code or a long text aloud instead of saving it with write_file; writes a file whose content has errors; saves a memory fact
the user did not clearly state; claims an action happened without the tool call for it; deletes files or runs a changing command
without asking first and getting a yes in a later turn (calling delete_files, run_command or apply_code_change without a
confirmation code is fine: that only prepares the action and returns a code to ask with); sends an email or WhatsApp message or
creates an event without first telling the user what will be sent and getting a yes in a later turn; answers in a language other than Brazilian Portuguese; writes long or
list-like answers unfit for speech; or answers something clearly not addressed to it instead of replying exactly [ignorar].
Return only JSON: {"ok": true or false, "reason": "one or two sentences"}

Conversation:
"""
JUDGE_TEXT_PROMPT = """You review a training conversation for Iris, a Brazilian Portuguese assistant answering in a terminal
(written answers: markdown, lists and code blocks are fine, and long answers are fine when the question needs them). Tool results are simulated.
Fail it if the assistant: states something factually wrong or outdated as if current; invents facts, numbers, versions, URLs or names that
neither the user nor a tool result gave; writes code, YAML, commands or configuration with errors that would not work as written (wrong
keys, invalid syntax, deprecated options, missing pieces the user asked for, insecure defaults without a warning); claims an action happened
without the tool call for it; replaces a file, runs a changing command, sends an email or message or creates an event without asking
first and getting a yes in a later turn (the first
call that only prepares the action is fine); answers in a language other than Brazilian Portuguese when the user did not ask for another;
is vague, padded or misses part of the request; or gives risky medical, legal or financial guidance without suggesting a professional when it matters.
Return only JSON: {"ok": true or false, "reason": "one or two sentences"}

Conversation:
"""
JUDGE_STRICT = "claude-sonnet-5-5"
TEACHER_EXTRA = {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}

CATEGORIES = {
    "open and close desktop apps (Chrome, Teams, VS Code, WhatsApp, Spotify, Excel, calculadora, terminal)": 40,
    "close one browser tab, current or by title": 20,
    "YouTube: play a video, open a creator channel, search": 35,
    "control media: pause, resume, next, volume": 20,
    "weather for a city, including the city the user lives in": 20,
    "list, find, open, create and move files and folders (Downloads, Documentos, projetos)": 40,
    "delete files: Iris asks first, the user then says yes or no in the next turn": 30,
    "read-only PowerShell commands (git status, docker ps, kubectl get pods, ping, ipconfig)": 30,
    "commands that change something: Iris asks first, the user answers in the next turn": 20,
    "look at the screen and click something on it (a video, link, button)": 30,
    "teach Iris a fact, correct a fact, ask what she remembers": 30,
    "small talk, thanks, greetings, jokes, how are you": 35,
    "questions about Iris's own code and requests to change her behavior": 20,
    "rate the previous answer as good or bad, or give the correct answer": 15,
    "close, hide or shut down Iris herself, move her to another monitor": 15,
    "text that is not addressed to Iris: TV or YouTube audio, other people talking, garbled fragments": 35,
    "garbled requests with speech recognition mistakes where the intent is still clear": 35,
    "technical questions the user might ask (docker, kubernetes, git, programming concepts)": 30,
    "current information that needs a web search (news, prices, football results, software releases, documentation)": 45,
    "questions answered from websites and documents the user saved in the library earlier": 35,
    "asking Iris to learn a website, documentation page or local document ('aprende esse site', 'guarda esse PDF')": 25,
}

EXTRA_CATEGORIES = {
    "general knowledge: history, geography, science, space, animals, curiosities": 40,
    "everyday life: cooking and recipes, cleaning, home repairs, plants, pets": 30,
    "health, exercise, sleep and nutrition basics, suggesting a doctor when it matters": 20,
    "personal finance and Brazilian everyday matters (Pix, imposto de renda, FGTS, CLT, INSS, boletos, contas)": 25,
    "quick math: calculations, percentages, unit and currency conversions, dates and time zones": 25,
    "translation and language help: how to say something in English or Spanish, word meanings, grammar doubts": 20,
    "planning and advice: study plans, travel ideas, organizing the day, habits, decisions": 25,
    "entertainment and culture: movies, series, books, music, games and football talk": 25,
    "emotional moments: the user is tired, stressed, sad, anxious or celebrating": 15,
    "create a file by voice: docker-compose, Dockerfile, script, config, shopping list or note, saved with write_file": 30,
    "read a file by voice (config, log, notes) and explain, summarize or fix it, replacing it only after the user agrees": 20,
}

TEXT_CATEGORIES = {
    "docker-compose files for real stacks (postgres, redis, nginx, keycloak, rabbitmq, kafka, grafana) with healthchecks, volumes, networks and env files": 40,
    "Dockerfiles: multi-stage builds, image size, caching, security, running as non-root": 25,
    "infrastructure: nginx and reverse proxies, TLS certificates, Kubernetes manifests, Helm, Docker Swarm, CI/CD pipelines (Azure DevOps, GitHub Actions)": 35,
    "automation scripts in PowerShell, bash and Python": 35,
    "debugging: the user pastes an error message, stack trace or log and wants the cause and the fix": 30,
    "SQL, databases, Linux administration and networking (DNS, ports, firewall, SSH)": 30,
    "programming and software design concepts explained in depth with examples": 25,
    "writing in Portuguese: professional emails, WhatsApp messages, LinkedIn posts, summaries, cover letters, reviewing a text": 35,
    "studying: school and university subjects (math, physics, chemistry, biology, history, Portuguese) explained step by step": 25,
    "research questions answered with web_search, citing the sources": 25,
    "comparisons and recommendations: laptops, phones, frameworks, cloud services, internet and phone plans": 20,
    "long open conversations: the user brainstorms an idea, a business, a project or a career decision over several turns": 20,
}

COMMS_CATEGORIES = {
    "email by voice: check new emails, read one, search by sender or subject, summarize the inbox": 30,
    "reply to or write an email by voice: Iris drafts it, tells the gist, sends only after the user says yes in the next turn": 30,
    "WhatsApp by voice: who sent messages, read a chat, summarize a group": 25,
    "send a WhatsApp message by voice: Iris confirms contact and text and sends only after a yes in the next turn; sometimes the user changes the text first": 30,
    "calendar by voice: what is on today or this week, create an appointment with confirmation, notice conflicts": 25,
    "projects by voice: create a new project (React, Node, Python, .NET), clone a git repository, open it in VS Code, install dependencies and run it, asking before commands that change something": 35,
    "mixed tasks across tools: read an email and add the meeting to the calendar, tell someone on WhatsApp you are late, find a file and email it": 25,
}

COMMS_TEXT_CATEGORIES = {
    "inbox triage and careful replies to difficult emails (client complaint, salary talk, declining a meeting), sending only after confirmation": 20,
    "start a project end to end: clone or create it, write the files, docker-compose and README, run it, asking before changing commands": 25,
}

COMMS_PROMPT = """
You can read and send the user's email (list_emails, read_email, send_email), read and send WhatsApp messages
(list_whatsapp_chats, read_whatsapp_chat, send_whatsapp_message) and see and create calendar events (list_events, create_event).
Summarize emails and chats in a few spoken words instead of reading them in full. Sending and creating always go in two steps: tell the
user who it goes to and the gist, ask, and only send after they say yes. To start a project, create the folder and files yourself and use
run_command for git clone, package managers and running it, asking before commands that change something."""

VOICE = "voice"
TEXT = "text"

USER_NAMES = ["Gabriel", "Ana", "Lucas", "Mariana", "Rafael", "Juliana", "Pedro", "Camila", "Bruno", "Larissa"]

LIBRARY_PROMPT = """
You also have a library of websites and documents the user asked you to learn. For questions about those topics, call
search_library first and answer from the excerpts, mentioning the source. When the user asks you to learn a page or file
('aprende esse site', 'guarda esse documento'), call learn_url with the URL, the file path or current_page, then confirm briefly.
Prefer search_library for saved topics and web_search for anything current."""

SCENARIO_PROMPT = """You create test scenarios for Iris, a Brazilian Portuguese assistant used by a person in Brazil who works with technology.
{channel}
Write {count} varied scenarios for this category: {category}

Return only a JSON array. Each item:
{{"turns": ["what the user says first", "optional follow-up in the next turn"],
  "screen": "short description of what is on the screen, only if the scenario needs it",
  "folder": ["file names that a folder listing or search would return, only if needed"],
  "command_output": "plausible output of the command, only if needed",
  "search_results": [{{"title": "...", "url": "https://...", "snippet": "..."}}],
  "library": [{{"source": "title or URL of a saved page", "excerpt": "relevant text from it"}}],
  "page": {{"title": "page open in the browser", "url": "https://..."}},
  "file_content": "full content of the file the user refers to, only if the scenario reads a file",
  "emails": [{{"id": "m1", "from": "Name <email>", "subject": "...", "date": "2026-10-12 09:14", "body": "..."}}],
  "chats": [{{"chat": "contact or group name", "unread": 2, "messages": ["Name: text", "..."]}}],
  "events": [{{"title": "...", "start": "2026-10-13T10:00", "end": "2026-10-13T11:00"}}]}}
Fill emails, chats and events only when the scenario needs the inbox, WhatsApp or the calendar.
Fill search_results only for web search scenarios, library only for library scenarios and page only when the user refers to
the page open in the browser. Use realistic, plausible content.
Use one turn for most scenarios and two or three turns when the category needs a follow-up. Vary vocabulary, length, tone and difficulty."""

VOICE_CHANNEL = """The user talks to Iris by voice; the words come from speech recognition, so about a third of the scenarios should include
realistic transcription noise in Brazilian Portuguese (wrong accents, merged or split words, misheard names like "crônio" for Chrome)."""
TEXT_CHANNEL = """The user types to Iris in a terminal, so there is no transcription noise. Requests can be long and detailed and may include
pasted code, logs, errors or texts inside the turn. Use two or three turns when a follow-up makes sense (adjust, explain a part, go deeper)."""

KNOWLEDGE = [
    "O usuário mora em Curitiba, PR.",
    "O usuário trabalha com tecnologia e usa muito o terminal.",
    "Fabio Akita é um canal de programação no YouTube que o usuário acompanha.",
]


@dataclass
class Scenario:
    category: str
    turns: list[str]
    screen: str = ""
    folder: list[str] | None = None
    command_output: str = ""
    search_results: list[dict] | None = None
    library: list[dict] | None = None
    page: dict | None = None
    file_content: str = ""
    profile: str = VOICE
    strict: bool = False
    comms: bool = False
    emails: list[dict] | None = None
    chats: list[dict] | None = None
    events: list[dict] | None = None


class FakeLauncher:
    def launch(self, name):
        return f"Opened {name}"

    def close(self, name):
        return f"Asked 1 window(s) of {name} to close"

    def open_url(self, target):
        return f"Opened {target if target.startswith('http') else 'https://www.google.com/search?q=' + target}"

    def youtube(self, query, kind="video"):
        return f"Opened {kind} '{query}' on YouTube"


class FakeKeys:
    def media(self, action):
        return f"Sent {action}"

    def close_tab(self, match=None):
        return f"Closed the tab '{match or 'current'}'"


class FakeScreen:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def describe(self, question, monitor=None):
        return self.scenario.screen or "A browser window with the Google home page."

    def click(self, target, monitor=None):
        return f"Clicked '{target}'"


class FakeWindow:
    def move_to_screen(self, number):
        return f"Moved to monitor {number}"

    def request_exit(self, mode):
        pass


class FakeFiles:
    def __init__(self, scenario: Scenario):
        self.names = scenario.folder or ["relatorio.pdf", "setup.exe", "notas.txt"]
        self.content = scenario.file_content

    def list(self, folder):
        return f"{folder} has {len(self.names)} items, newest first:\n" + "\n".join(f"{n} (1.2 MB, 2026-10-07)" for n in self.names)

    def find(self, pattern, folder="~"):
        return "\n".join(f"C:\\Users\\usuario\\Downloads\\{n}" for n in self.names)

    def create_folder(self, folder):
        return f"Folder ready: {folder}"

    def move(self, sources, destination):
        return "\n".join(f"{s} -> {destination}" for s in sources)

    def open(self, raw):
        return f"Opened {raw}"

    def read(self, path):
        return f"{path}:\n{self.content}" if self.content else f"{path}:\nversion: '3'\nservices:\n  app:\n    image: node:20"

    def write(self, path, content, overwrite=False):
        return f"Wrote {len(content.splitlines())} lines to {path}"

    def check_deletable(self, paths):
        return [Path(p) for p in paths]

    def delete(self, paths):
        return f"Sent {len(paths)} item(s) to the Recycle Bin"


class FakeWeather:
    def current(self, city):
        temperature = random.randint(12, 32)
        return {"city": city, "temperature_c": temperature, "feels_like_c": temperature + random.randint(-2, 2), "humidity": random.randint(40, 90), "wind_kmh": random.randint(3, 25), "conditions": random.choice(["céu limpo", "parcialmente nublado", "nublado", "chuva fraca"])}


class FakeRecorder:
    def rate_last(self, rating, correction=None):
        return f"Rated the last answer as {rating}"


class FakeJob:
    id = "214500"
    branch = "iris/change-214500"


class FakeWorker:
    jobs = {}

    def analyze(self, question):
        return "A Iris usa o Whisper para transcrever, o Claude para responder e a voz neural da Microsoft para falar."

    def start(self, instruction):
        return FakeJob()

    def apply(self, job_id):
        return f"Applied 2 changed files from iris/change-{job_id}"

    def discard(self, job_id):
        return f"Discarded iris/change-{job_id}"


class FakeSearch:
    def __init__(self, scenario: Scenario):
        self.results = scenario.search_results or [{"title": "Resultado", "url": "https://example.com", "snippet": "Sem detalhes."}]

    def search(self, query):
        return "\n".join(f"{r.get('title')} - {r.get('url')}\n{r.get('snippet')}" for r in self.results[:5])


class FakeLibrary:
    def __init__(self, scenario: Scenario):
        self.items = scenario.library or []
        self.page = scenario.page or {"title": "Página atual", "url": "https://example.com"}

    def search(self, query):
        if not self.items:
            return "Nothing in the library about this"
        return "\n\n".join(f"[{i.get('source')}]\n{i.get('excerpt')}" for i in self.items[:4])

    def learn(self, source):
        if source == "current_page":
            return f"Saved '{self.page.get('title')}' ({self.page.get('url')}) to the library: 12 excerpts"
        return f"Saved '{source}' to the library: 9 excerpts"


class FakeMailbox:
    def __init__(self, scenario: Scenario):
        self.emails = scenario.emails or [{"id": "m1", "from": "Equipe <noreply@example.com>", "subject": "Boas-vindas", "date": "2026-10-12 08:00", "body": "Olá!"}]

    def search(self, query, unread_only, limit):
        return "\n".join(f"{e.get('id')} | {e.get('from')} | {e.get('subject')} | {e.get('date')} | {str(e.get('body', ''))[:80]}" for e in self.emails[:limit])

    def read(self, message_id):
        email = next((e for e in self.emails if e.get("id") == message_id), self.emails[0])
        return f"From: {email.get('from')}\nSubject: {email.get('subject')}\nDate: {email.get('date')}\n\n{email.get('body')}"

    def send(self, to, subject, body, reply_to_id):
        return f"Email sent to {', '.join(to)}"


class FakeMessenger:
    def __init__(self, scenario: Scenario):
        self.chats_data = scenario.chats or [{"chat": "Família", "unread": 0, "messages": ["Mãe: Bom dia!"]}]

    def chats(self, unread_only):
        return "\n".join(f"{c.get('chat')} ({c.get('unread', 0)} unread): {(c.get('messages') or [''])[-1]}" for c in self.chats_data)

    def read(self, chat, limit):
        wanted = normalize(chat)
        found = next((c for c in self.chats_data if normalize(str(c.get("chat", ""))) in wanted or wanted in normalize(str(c.get("chat", "")))), None)
        return "\n".join(found.get("messages", [])[-limit:]) if found else f"No chat named {chat}"

    def send(self, chat, text):
        return f"Message sent to {chat}"


class FakeCalendar:
    def __init__(self, scenario: Scenario):
        self.items = scenario.events or []

    def events(self, date_from, date_to):
        if not self.items:
            return f"No events between {date_from} and {date_to}"
        return "\n".join(f"{e.get('start')} - {e.get('end')}: {e.get('title')}" for e in self.items)

    def create(self, title, start, end, location):
        return f"Event '{title}' created for {start}"


class Turn:
    value = 0


def build_tools(scenario: Scenario, memory: SQLiteMemory, turn: Turn) -> ToolRegistry:
    current = lambda: turn.value  # noqa: E731
    launcher, keys, files, window, worker = FakeLauncher(), FakeKeys(), FakeFiles(scenario), FakeWindow(), FakeWorker()
    output = scenario.command_output or "Exit code 0"
    tools = [
            RememberTool(memory),
            ForgetTool(memory),
            WeatherTool(FakeWeather()),
            OpenAppTool(launcher),
            CloseAppTool(launcher),
            CloseTabTool(keys),
            MediaControlTool(keys),
            LookAtScreenTool(FakeScreen(scenario)),
            ClickOnScreenTool(FakeScreen(scenario)),
            OpenUrlTool(launcher),
            YoutubeTool(launcher),
            RateAnswerTool(FakeRecorder()),
            ListFolderTool(files),
            FindFilesTool(files),
            CreateFolderTool(files),
            MoveFilesTool(files),
            OpenPathTool(files),
            ReadFileTool(files),
            WriteFileTool(files),
            DeleteFilesTool(files, current),
            RunCommandTool(current, runner=lambda command, cwd: output if output.startswith("Exit") else f"Exit code 0\n{output}"),
            AnalyzeOwnCodeTool(worker),
            StartCodeChangeTool(worker),
            CodeChangesStatusTool(worker),
            ApplyCodeChangeTool(worker, current, lambda: None),
            WebSearchTool(FakeSearch(scenario)),
            SearchLibraryTool(FakeLibrary(scenario)),
            LearnUrlTool(FakeLibrary(scenario)),
    ]
    if scenario.comms:
        mailbox, messenger, calendar = FakeMailbox(scenario), FakeMessenger(scenario), FakeCalendar(scenario)
        tools += [
            ListEmailsTool(mailbox),
            ReadEmailTool(mailbox),
            SendEmailTool(mailbox, current),
            ListChatsTool(messenger),
            ReadChatTool(messenger),
            SendChatMessageTool(messenger, current),
            ListEventsTool(calendar),
            CreateEventTool(calendar, current),
        ]
    if scenario.profile == VOICE:
        tools += [MoveWindowTool(window), ExitTool(window)]
    return ToolRegistry(tools)


class AllowAll:
    def approve(self, call):
        return True


def tool_schemas(tools: ToolRegistry) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools.all()]


def spoken(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F*#`]", "", text)).strip()


def to_training_messages(system: str, messages, profile: str = VOICE) -> list[dict]:
    converted = [{"role": "system", "content": system}]
    for message in messages:
        if message.tool_results:
            for result in message.tool_results:
                converted.append({"role": "tool", "content": result.content})
        elif message.role is Role.USER:
            converted.append({"role": "user", "content": message.text})
        else:
            text = message.text if message.text.startswith("[") or profile == TEXT else spoken(message.text)
            if message.tool_calls and not any(c.name in SLOW_TOOLS for c in message.tool_calls):
                text = ""
            if random.random() > 0.15:
                text = NAME.sub("", text).strip()
                text = text[:1].upper() + text[1:]
            entry = {"role": "assistant", "content": text}
            if message.tool_calls:
                entry["tool_calls"] = [{"type": "function", "function": {"name": c.name, "arguments": c.input}} for c in message.tool_calls]
            converted.append(entry)
    return converted


def generate_scenarios(client: anthropic.Anthropic, per_category_scale: float, plan: list[tuple[str, int, str, bool, bool]]) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for category, count, profile, strict, comms in plan:
        wanted = max(1, round(count * per_category_scale))
        response = client.messages.create(
            model=TEACHER,
            max_tokens=16000,
            thinking={"type": "between_tools"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": SCENARIO_PROMPT.format(
                count=wanted, category=category, channel=TEXT_CHANNEL if profile == TEXT else VOICE_CHANNEL,
            )}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        match = re.search(r"\[.*\]", text, re.DOTALL)
        items = json.loads(match.group(0)) if match else []
        for item in items[:wanted]:
            if item.get("turns"):
                scenarios.append(Scenario(
                    category, item["turns"][:3], item.get("screen", ""), item.get("folder"), item.get("command_output", ""),
                    item.get("search_results"), item.get("library"), item.get("page"),
                    item.get("file_content") or "", profile, strict, comms,
                    item.get("emails"), item.get("chats"), item.get("events"),
                ))
        print(f"{len(items):3d} scenarios: {category}", flush=True)
    return scenarios


def run_scenario(scenario: Scenario, api_key: str, base_prompt: str) -> dict:
    user_name = random.choice(USER_NAMES)
    system_prompt = base_prompt.replace("{user}", user_name)
    if "search_library first" not in system_prompt:
        system_prompt += LIBRARY_PROMPT
    if scenario.comms:
        system_prompt += COMMS_PROMPT
    if scenario.profile == TEXT:
        system_prompt += "\n" + resources.files("iris.agent").joinpath("prompts/cli.md").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        memory = SQLiteMemory(Path(folder) / "facts.db")
        for fact in KNOWLEDGE:
            memory.remember(fact)
        turn = Turn()
        tools = build_tools(scenario, memory, turn)
        loop = AgentLoop(
            llm=ClaudeProvider(api_key, TEACHER, max_tokens=4096 if scenario.profile == TEXT else 1024, extra=TEACHER_EXTRA),
            tools=tools,
            guardrail=Guardrail(AllowAll()),
            knowledge=memory,
            recorder=type("NoRecorder", (), {"record": lambda self, interaction: None})(),
            system_prompt=system_prompt,
        )
        conversation = Conversation(loop)
        for text in scenario.turns:
            turn.value += 1
            conversation.ask(text)
        system = loop._build_system(memory.search(scenario.turns[0]))
        memory.db.close()
    messages = to_training_messages(system, conversation.history, scenario.profile)
    verdict = judge(api_key, messages, user_name, scenario)
    return {"category": scenario.category, "messages": messages, "tools": tool_schemas(tools), "judge": verdict}


def judge(api_key: str, messages: list[dict], user_name: str, scenario: Scenario) -> dict:
    transcript = [
        f"(Context the assistant had: the user's name is {user_name}; saved facts: {' '.join(KNOWLEDGE)}. "
        "Using the name or these facts is not invention.)"
    ]
    for m in messages[1:]:
        calls = f" [tools: {json.dumps([c['function'] for c in m.get('tool_calls', [])], ensure_ascii=False)}]" if m.get("tool_calls") else ""
        transcript.append(f"{m['role'].upper()}: {m['content']}{calls}")
    response = anthropic.Anthropic(api_key=api_key).messages.create(
        model=JUDGE_STRICT if scenario.strict else JUDGE,
        max_tokens=1500,
        thinking={"type": "between_tools"} if scenario.strict else {"type": "disabled"},
        messages=[{"role": "user", "content": (JUDGE_TEXT_PROMPT if scenario.profile == TEXT else JUDGE_PROMPT) + "\n".join(transcript)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(match.group(0)) if match else {"ok": False, "reason": "no verdict"}
    except json.JSONDecodeError:
        return {"ok": False, "reason": "invalid verdict"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a distilled tool-use dataset for Iris with Claude as the teacher")
    parser.add_argument("--out", type=Path, default=Path("dataset/synthetic.jsonl"))
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier on the per-category scenario counts")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--set", choices=["base", "extra", "comms", "all"], default="all",
                        help="base: tools and voice; extra: every other subject; comms: email, WhatsApp, calendar and projects")
    args = parser.parse_args()

    api_key = get_secret(ANTHROPIC_KEY)
    if not api_key:
        raise SystemExit("Anthropic API key not found in the Windows vault (service 'iris')")
    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = resources.files("iris.agent").joinpath("prompts/system.md").read_text(encoding="utf-8")

    plan = []
    if args.set in ("base", "all"):
        plan += [(c, n, VOICE, False, False) for c, n in CATEGORIES.items()]
    if args.set in ("extra", "all"):
        plan += [(c, n, VOICE, True, False) for c, n in EXTRA_CATEGORIES.items()]
        plan += [(c, n, TEXT, True, False) for c, n in TEXT_CATEGORIES.items()]
    if args.set in ("comms", "all"):
        plan += [(c, n, VOICE, True, True) for c, n in COMMS_CATEGORIES.items()]
        plan += [(c, n, TEXT, True, True) for c, n in COMMS_TEXT_CATEGORIES.items()]
    scenarios = generate_scenarios(client, args.scale, plan)
    random.shuffle(scenarios)
    print(f"Running {len(scenarios)} scenarios with {args.workers} workers", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    done = failed = rejected = 0
    with args.out.open("w", encoding="utf-8") as file, ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(run_scenario, s, api_key, system_prompt): s for s in scenarios}
        for future in as_completed(futures):
            try:
                example = future.result()
                if not example["judge"].get("ok"):
                    rejected += 1
                    print(f"rejected: {futures[future].turns[0][:60]!r}: {example['judge'].get('reason')}", flush=True)
                    continue
                with lock:
                    file.write(json.dumps(example, ensure_ascii=False) + "\n")
                    file.flush()
                done += 1
            except Exception as exc:
                failed += 1
                print(f"failed: {futures[future].turns[0][:60]!r}: {exc}", flush=True)
            if (done + failed + rejected) % 25 == 0:
                print(f"{done} kept, {rejected} rejected, {failed} failed", flush=True)
    print(f"Finished: {done} examples in {args.out}, {rejected} rejected by the judge, {failed} failed")


if __name__ == "__main__":
    main()
