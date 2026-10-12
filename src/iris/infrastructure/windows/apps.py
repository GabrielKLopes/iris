import difflib
import json
import os
import re
import subprocess
import urllib.request
import webbrowser
from urllib.parse import quote_plus

from iris.application.intent import normalize

ALIASES = {
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "code": "visual studio code",
    "navegador": "google chrome",
    "chrome": "google chrome",
    "teams": "microsoft teams",
    "zap": "whatsapp",
    "explorador": "explorador de arquivos",
    "arquivos": "explorador de arquivos",
    "bloco de notas": "bloco de notas",
    "configuracoes": "configuracoes",
}

COMMON_APPS = [
    "google chrome", "microsoft edge", "microsoft teams", "visual studio code", "whatsapp", "spotify", "outlook",
    "outlook (classic)", "excel", "word", "powerpoint", "discord", "steam", "dbeaver", "postman", "docker desktop",
    "calculadora", "bloco de notas", "configuracoes", "explorador de arquivos",
]

PROCESS_NAMES = {
    "google chrome": "chrome",
    "microsoft edge": "msedge",
    "microsoft teams": "ms-teams",
    "visual studio code": "Code",
    "whatsapp": "WhatsApp",
    "spotify": "Spotify",
    "outlook": "olk",
    "outlook (classic)": "OUTLOOK",
    "excel": "EXCEL",
    "word": "WINWORD",
    "powerpoint": "POWERPNT",
    "calculadora": "CalculatorApp",
    "discord": "Discord",
    "steam": "steam",
    "bloco de notas": "notepad",
}

COMMANDS = {
    "explorador de arquivos": "explorer",
    "terminal": "wt",
    "prompt de comando": "cmd",
    "gerenciador de tarefas": "taskmgr",
}


def list_start_apps() -> dict[str, str]:
    output = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=20,
    ).stdout
    apps = json.loads(output or "[]")
    if isinstance(apps, dict):
        apps = [apps]
    return {normalize(app["Name"]): app["AppID"] for app in apps if "uninstall" not in app["Name"].lower()}


class WindowsAppLauncher:
    def __init__(self, apps: dict[str, str] | None = None):
        self._apps = apps

    def apps(self) -> dict[str, str]:
        if self._apps is None:
            self._apps = list_start_apps()
        return self._apps

    def find(self, name: str) -> tuple[str, str] | None:
        wanted = ALIASES.get(normalize(name), normalize(name))
        apps = self.apps()
        if wanted in apps:
            return wanted, apps[wanted]
        by_word = [key for key in apps if key.startswith(wanted + " ") or f" {wanted}" in f" {key}"]
        if by_word:
            best = min(by_word, key=len)
            return best, apps[best]
        close = difflib.get_close_matches(wanted, apps.keys(), n=1, cutoff=0.8)
        return (close[0], apps[close[0]]) if close else None

    def common(self) -> list[str]:
        installed = self.apps()
        return [name for name in COMMON_APPS if name in installed]

    def launch(self, name: str) -> str:
        command = COMMANDS.get(ALIASES.get(normalize(name), normalize(name)))
        if command:
            subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Opened {name}"
        match = self.find(name)
        if match is None:
            hint = f" Commonly used installed apps: {', '.join(self.common())}."
            return f"Application '{name}' was not found.{hint} If one of them is clearly what the user meant, open it."
        title, app_id = match
        os.startfile(f"shell:AppsFolder\\{app_id}")
        return f"Opened {title}"

    def close(self, name: str) -> str:
        match = self.find(name)
        key = match[0] if match else ALIASES.get(normalize(name), normalize(name))
        process = PROCESS_NAMES.get(key, key.split()[0] if key else name)
        script = (
            f"$p = Get-Process -Name '{process}' -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne 0 }}; "
            "$p | ForEach-Object { [void]$_.CloseMainWindow() }; $p.Count"
        )
        output = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        ).stdout.strip()
        closed = int(output) if output.isdigit() else 0
        if not closed:
            return f"No open window found for '{name}' (process {process})"
        return f"Asked {closed} window(s) of {key} to close"

    def _youtube_html(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR"})
        return urllib.request.urlopen(request, timeout=8).read().decode("utf-8", "replace")

    def youtube(self, query: str, kind: str = "video") -> str:
        search = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        url, found = search, ""
        try:
            if kind == "channel":
                html = self._youtube_html(search + "&sp=EgIQAg%253D%253D")
                handle = re.search(r'"canonicalBaseUrl":"(/@[^"]+)"', html)
                title = re.search(r'"channelRenderer":\{"channelId":"[^"]+","title":\{"simpleText":"([^"]+)"', html)
                if handle:
                    url = f"https://www.youtube.com{handle.group(1)}"
                    found = f"channel '{title.group(1) if title else handle.group(1)}'"
            elif kind == "video":
                html = self._youtube_html(search)
                video = re.search(r'"videoId":"([\w-]{11})"', html)
                title = re.search(r'"videoRenderer":\{"videoId":"[\w-]{11}".*?"title":\{"runs":\[\{"text":"([^"]+)"', html)
                if video:
                    url = f"https://www.youtube.com/watch?v={video.group(1)}"
                    found = f"video '{title.group(1) if title else video.group(1)}'"
        except Exception:
            pass
        webbrowser.open(url)
        if found:
            return f"Opened {found}: {url}. If the name does not match what the user asked, say so."
        return f"Opened YouTube search results for '{query}': {url}"

    def open_url(self, target: str) -> str:
        url = target if target.startswith(("http://", "https://")) else None
        if url is None and "." in target and " " not in target.strip():
            url = f"https://{target.strip()}"
        if url is None:
            url = f"https://www.google.com/search?q={quote_plus(target)}"
        webbrowser.open(url)
        return f"Opened {url}"
