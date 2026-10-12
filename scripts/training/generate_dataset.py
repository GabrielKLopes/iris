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
General knowledge that is correct (science, history, geography, how things work, plausible estimates phrased as approximate with words like 'cerca de', 'uns', 'em média', 'aproximadamente') is fine without a tool; only facts about the user, prices, news and other current data must come from the user or a tool result. Return only JSON: {"ok": true or false, "reason": "one or two sentences"}

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
General knowledge that is correct (science, history, geography, how things work, plausible estimates phrased as approximate with words like 'cerca de', 'uns', 'em média', 'aproximadamente') is fine without a tool; only facts about the user, prices, news and other current data must come from the user or a tool result. Return only JSON: {"ok": true or false, "reason": "one or two sentences"}

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

WORLD_VOICE_CATEGORIES = {
    "consumer rights in Brazil: returns, warranties, Procon, abusive charges, flight delays": 25,
    "health questions: symptoms, medicines, exams, when to see a doctor, always careful and never diagnosing": 30,
    "mental health and emotions: anxiety, sadness, stress, loneliness, burnout, answered with care and CVV when needed": 25,
    "relationships, friendship and family conflicts, asking for advice": 25,
    "parenting: babies, children's sleep, school, screen time, tantrums, activities for kids": 25,
    "school help for children and teenagers: homework in math, Portuguese, history, science": 30,
    "science curiosities: physics, chemistry, biology, space, the human body, explained simply": 30,
    "history and geography of Brazil and the world": 25,
    "philosophy, religion and big questions, answered neutrally and respectfully": 20,
    "arts, literature, poetry, cinema and series recommendations and discussions": 25,
    "music: genres, artists, learning an instrument, music theory basics": 20,
    "sports: rules, history, training, football talk about Brazilian clubs": 25,
    "cars and motorcycles: maintenance, strange noises, documents, IPVA, buying a used car": 25,
    "home: repairs, cleaning tricks, organization, energy bill savings, decoration": 25,
    "gardening and plants, pets and animal care": 25,
    "cooking: recipes, substitutions, what to cook with what is in the fridge, food storage": 30,
    "nutrition and fitness: diets, workouts, running, weight loss, sleep habits": 25,
    "money: budgeting, debt, credit card, Pix, savings, investing basics like CDB, Tesouro Direto and index funds": 30,
    "taxes and bureaucracy in Brazil: imposto de renda, MEI, CPF, documents, INSS, FGTS, gov.br": 25,
    "work and career: job interviews, resumes, salary negotiation, changing careers, dealing with a difficult boss": 25,
    "small business: pricing, selling on Instagram and WhatsApp, customer service, MEI, marketing": 25,
    "phone and computer help for non-technical people: Wi-Fi, printer, storage full, WhatsApp backup, slow PC, scams": 30,
    "travel: planning trips in Brazil and abroad, documents, packing, budget, what to visit": 25,
    "language learning: English and Spanish practice, translations, pronunciation tips": 25,
    "math and logic: mental math, percentages, unit conversions, riddles and puzzles": 25,
    "trivia, jokes, games and fun conversation": 25,
    "emergencies and first aid: burns, choking, fainting, what to do and when to call 192 or 193": 20,
    "environment, recycling and climate, explained simply": 15,
    "how society works: elections, the three powers, laws, rights, explained neutrally without taking political sides": 20,
    "teach Iris a personal fact or a nickname of their own (a person, a place, a routine), then use it later; facts about everyday life, never workplace jargon": 30,
    "ask Iris to set up something in the computer in plain words: open a site, find a file, create a folder for a family event": 25,
}

WORLD_TEXT_CATEGORIES = {
    "writing: stories, poems, song lyrics, birthday messages, wedding speeches, social media captions": 30,
    "formal writing: complaint letters, requests to the landlord, school emails, Procon complaints, cover letters": 25,
    "studying: step-by-step explanations of math, physics, chemistry and biology exercises at school and university level": 30,
    "essays and ENEM redação: structure, argument, correction of a text the user pastes": 20,
    "summaries and explanations of books, historical events and scientific concepts": 25,
    "programming in many languages and levels: Python, JavaScript, Java, C#, SQL, beginners and experienced": 30,
    "data and spreadsheets: Excel and Google Sheets formulas, pivot tables, charts, cleaning data": 25,
    "statistics and data science explained: mean, median, standard deviation, probability, regression, with examples": 25,
    "machine learning and artificial intelligence explained: how models learn, neural networks, overfitting, with simple code": 20,
    "financial planning in detail: monthly budget tables, debt payoff plans, comparing investments with calculations": 20,
    "planning: weekly meal plans, study schedules, workout programs, trip itineraries in tables": 25,
    "business: business plans, pricing calculations, marketing plans, customer messages for small shops": 20,
    "legal and bureaucratic explanations in Brazil: contracts, rent, labor rights (CLT), consumer code, with care to suggest a lawyer": 20,
    "health information in depth: explaining exam results and conditions carefully, always recommending a doctor": 20,
    "translation and language: translating texts, explaining grammar, correcting texts in English or Spanish": 25,
    "debate and critical thinking: pros and cons of decisions, comparing options, checking if a news item is fake": 20,
    "computers for everyone: formatting Windows, choosing a laptop, backups, security, protecting from scams": 20,
    "infrastructure and DevOps: docker, Linux, networks, cloud, CI/CD": 15,
    "math problems: algebra, geometry, financial math, solved step by step": 25,
    "history, philosophy and sociology essays and explanations for students": 20,
    "creative projects: game ideas, YouTube channel scripts, podcast outlines, story worlds": 20,
    "science projects and experiments for school, explained safely": 15,
    "long open conversations about life decisions, hobbies or ideas over several turns": 20,
}

VOICE = "voice"
TEXT = "text"

USER_NAMES = ["Gabriel", "Ana", "Lucas", "Mariana", "Rafael", "Juliana", "Pedro", "Camila", "Bruno", "Larissa"]

LIBRARY_PROMPT = """
You also have a library of websites and documents the user asked you to learn. For questions about those topics, call
search_library first and answer from the excerpts, mentioning the source. When the user asks you to learn a page or file
('aprende esse site', 'guarda esse documento'), call learn_url with the URL, the file path or current_page, then confirm briefly.
Prefer search_library for saved topics and web_search for anything current."""

DEFAULT_PERSONA = "a person in Brazil who works with technology"

SCENARIO_PROMPT = """You create test scenarios for Iris, a Brazilian Portuguese assistant used by all kinds of people in Brazil.
This batch's user: {persona}. Write the requests the way this person would really talk, about their own life; do not make them a
programmer or IT worker unless the persona says so, and never use workplace jargon from a specific company.
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

PERSONAS = [
    {"name": "Camila", "about": "a nursing student in Recife, she/her", "facts": ["A usuária mora em Recife, PE.", "A usuária estuda enfermagem na faculdade.", "A usuária tem uma gata chamada Pipoca."]},
    {"name": "Seu Antônio", "about": "a retired teacher in Porto Alegre learning to use the computer, he/him", "facts": ["O usuário é professor aposentado e mora em Porto Alegre, RS.", "O usuário prefere respostas bem curtas.", "O usuário torce para o Grêmio."]},
    {"name": "Josué", "about": "a truck driver from Goiás who talks to the assistant on breaks, he/him", "facts": ["O usuário é caminhoneiro e mora em Rio Verde, GO.", "O usuário tem dois filhos, a Laura de 8 anos e o Davi de 5.", "O usuário gosta de música sertaneja."]},
    {"name": "Dona Lúcia", "about": "a small bakery owner in Belo Horizonte, she/her", "facts": ["A usuária tem uma padaria em Belo Horizonte, MG.", "A usuária acorda às 4 da manhã.", "Quando a usuária fala 'a planilha', é a planilha de vendas da padaria."]},
    {"name": "Fernanda", "about": "a mother of two in São Paulo who works from home in customer service, she/her", "facts": ["A usuária mora em São Paulo, SP.", "A usuária tem dois filhos, o Pedro de 10 anos e a Bia de 3.", "O aniversário do marido da usuária é em 14 de março."]},
    {"name": "Kauã", "about": "a high school student in Manaus preparing for the ENEM, he/him", "facts": ["O usuário mora em Manaus, AM.", "O usuário está estudando para o ENEM e quer fazer medicina.", "O usuário joga futebol aos sábados."]},
    {"name": "Rogério", "about": "a nurse working night shifts in Salvador, he/him", "facts": ["O usuário é enfermeiro e trabalha no plantão noturno em Salvador, BA.", "O usuário torce para o Bahia.", "O usuário é vegetariano."]},
    {"name": "Larissa", "about": "a freelance graphic designer in Florianópolis, she/her", "facts": ["A usuária é designer gráfica freelancer em Florianópolis, SC.", "A usuária tem uma cachorra chamada Mel.", "A usuária está aprendendo inglês."]},
    {"name": "Thiago", "about": "a software developer in Campinas, he/him", "facts": ["O usuário é desenvolvedor de software e mora em Campinas, SP.", "O usuário usa o Spotify para ouvir podcasts.", "O usuário faz academia de manhã."]},
    {"name": "Doutora Renata", "about": "a lawyer in Brasília, she/her", "facts": ["A usuária é advogada em Brasília, DF.", "A usuária prefere respostas objetivas.", "A usuária corre aos domingos no Parque da Cidade."]},
    {"name": "Seu Valdir", "about": "a soy farmer in Mato Grosso do Sul, he/him", "facts": ["O usuário é produtor rural em Dourados, MS.", "O usuário tem uma caminhonete Hilux 2019.", "O usuário chama a esposa de Nena."]},
    {"name": "Bruno", "about": "a personal trainer in Rio de Janeiro, he/him", "facts": ["O usuário é personal trainer no Rio de Janeiro, RJ.", "O usuário torce para o Flamengo.", "O usuário atende alunos das 6h às 11h."]},
    {"name": "Iara", "about": "a musician who teaches guitar in Fortaleza, she/her", "facts": ["A usuária dá aulas de violão em Fortaleza, CE.", "A usuária gosta de MPB e de rock dos anos 80.", "A usuária tem um gato chamado Tom."]},
    {"name": "Paulo", "about": "an accountant in Ribeirão Preto, he/him", "facts": ["O usuário é contador em Ribeirão Preto, SP.", "O usuário tem diabetes tipo 2.", "O usuário gosta de cozinhar nos fins de semana."]},
    {"name": "Jéssica", "about": "a hairdresser with her own salon in Belém, she/her", "facts": ["A usuária tem um salão de beleza em Belém, PA.", "A usuária atende clientes pelo WhatsApp.", "A usuária chama a mãe de dona Célia."]},
    {"name": "Seu Raimundo", "about": "an elderly man in Natal who lives alone, he/him", "facts": ["O usuário tem 78 anos e mora sozinho em Natal, RN.", "O usuário toma remédio de pressão de manhã.", "A filha do usuário se chama Marta e mora em São Paulo."]},
    {"name": "Gabi", "about": "a gamer and streamer in Joinville, she/her", "facts": ["A usuária faz lives de jogos e mora em Joinville, SC.", "A usuária transmite na Twitch às terças e quintas.", "A usuária tem um PC com placa RTX 4060."]},
    {"name": "Marcos", "about": "a civil engineer in Vitória, he/him", "facts": ["O usuário é engenheiro civil em Vitória, ES.", "O usuário tem um Fiat Argo 2021.", "O usuário está reformando o apartamento."]},
    {"name": "Professora Ana", "about": "a primary school teacher in Teresina, she/her", "facts": ["A usuária é professora do ensino fundamental em Teresina, PI.", "A usuária dá aula para o 3º ano.", "A usuária gosta de ler romances."]},
    {"name": "Rafael", "about": "a delivery motorcyclist in Curitiba, he/him", "facts": ["O usuário é motoboy e mora em Curitiba, PR.", "O usuário tem uma moto Honda CG 160.", "O usuário está juntando dinheiro para casar."]},
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
    persona: int | None = None


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


def scenario_batch(client: anthropic.Anthropic, category: str, wanted: int, profile: str, strict: bool, comms: bool, persona: int | None) -> list[Scenario]:
    response = client.messages.create(
        model=TEACHER,
        max_tokens=16000,
        thinking={"type": "between_tools"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": SCENARIO_PROMPT.format(
            count=wanted, category=category, channel=TEXT_CHANNEL if profile == TEXT else VOICE_CHANNEL,
            persona=PERSONAS[persona]["about"] if persona is not None else DEFAULT_PERSONA,
        )}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\[.*\]", text, re.DOTALL)
    items = json.loads(match.group(0)) if match else []
    return [
        Scenario(
            category, item["turns"][:3], item.get("screen", ""), item.get("folder"), item.get("command_output", ""),
            item.get("search_results"), item.get("library"), item.get("page"),
            item.get("file_content") or "", profile, strict, comms,
            item.get("emails"), item.get("chats"), item.get("events"), persona,
        )
        for item in items[:wanted]
        if item.get("turns")
    ]


def generate_scenarios(
    client: anthropic.Anthropic, per_category_scale: float, plan: list[tuple[str, int, str, bool, bool]], varied: bool = False, chunk: int = 8,
) -> list[Scenario]:
    jobs = []
    for category, count, profile, strict, comms in plan:
        wanted = max(1, round(count * per_category_scale))
        if not varied:
            jobs.append((category, wanted, profile, strict, comms, None))
            continue
        while wanted > 0:
            size = min(chunk, wanted)
            jobs.append((category, size, profile, strict, comms, random.randrange(len(PERSONAS))))
            wanted -= size
    scenarios: list[Scenario] = []
    with ThreadPoolExecutor(6) as pool:
        for batch in pool.map(lambda job: scenario_batch(client, *job), jobs):
            scenarios.extend(batch)
    print(f"{len(scenarios)} scenarios from {len(jobs)} batches", flush=True)
    return scenarios


def run_scenario(scenario: Scenario, api_key: str, base_prompt: str) -> dict:
    persona = PERSONAS[scenario.persona] if scenario.persona is not None else None
    user_name = persona["name"] if persona else random.choice(USER_NAMES)
    system_prompt = base_prompt.replace("{user}", user_name).replace("{language}", "Brazilian Portuguese")
    if "search_library first" not in system_prompt:
        system_prompt += LIBRARY_PROMPT
    if scenario.comms:
        system_prompt += COMMS_PROMPT
    if scenario.profile == TEXT:
        system_prompt += "\n" + resources.files("iris.agent").joinpath("prompts/cli.md").read_text(encoding="utf-8")
    facts = persona["facts"] if persona else KNOWLEDGE
    with tempfile.TemporaryDirectory() as folder:
        memory = SQLiteMemory(Path(folder) / "facts.db")
        for fact in facts:
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
    verdict = judge(api_key, messages, user_name, scenario, facts)
    return {"category": scenario.category, "messages": messages, "tools": tool_schemas(tools), "judge": verdict}


def judge(api_key: str, messages: list[dict], user_name: str, scenario: Scenario, facts: list[str]) -> dict:
    transcript = [
        f"(Context the assistant had: the user's name is {user_name}; saved facts: {' '.join(facts)}. "
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
    parser.add_argument("--set", choices=["base", "extra", "comms", "world", "all"], default="all",
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
    if args.set in ("world", "all"):
        plan += [(c, n, VOICE, False, False) for c, n in WORLD_VOICE_CATEGORIES.items()]
        plan += [(c, n, TEXT, True, False) for c, n in WORLD_TEXT_CATEGORIES.items()]
    if args.set in ("comms", "all"):
        plan += [(c, n, VOICE, True, True) for c, n in COMMS_CATEGORIES.items()]
        plan += [(c, n, TEXT, True, True) for c, n in COMMS_TEXT_CATEGORIES.items()]
    scenarios = generate_scenarios(client, args.scale, plan, varied=args.set == "world")
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
