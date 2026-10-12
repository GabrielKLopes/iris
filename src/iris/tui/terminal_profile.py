from __future__ import annotations

import json
import os
import sys
from importlib import resources
from pathlib import Path

SCHEME = {
    "name": "Iris",
    "background": "#0D0B09",
    "foreground": "#EFE8DC",
    "cursorColor": "#E9B04C",
    "selectionBackground": "#3A3128",
    "black": "#0D0B09",
    "red": "#E5644F",
    "green": "#8E8758",
    "yellow": "#E9B04C",
    "blue": "#7AA2C9",
    "purple": "#B48EAD",
    "cyan": "#88B4A8",
    "white": "#D8CFC2",
    "brightBlack": "#5A5148",
    "brightRed": "#F07A66",
    "brightGreen": "#A9A26E",
    "brightYellow": "#FFD98A",
    "brightBlue": "#9BBCE0",
    "brightPurple": "#CBA6C3",
    "brightCyan": "#A3CEC2",
    "brightWhite": "#EFE8DC",
}


def fragment_file() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    if not base or not (Path(base) / "Microsoft" / "Windows Terminal").parent.exists():
        return None
    return Path(base) / "Microsoft" / "Windows Terminal" / "Fragments" / "Iris" / "iris.json"


def launcher() -> str:
    shim = Path(os.environ.get("LOCALAPPDATA", "")) / "iris" / "bin" / "iris.cmd"
    if shim.exists():
        return f'"{shim}"'
    return f'"{Path(sys.executable).with_name("iris.exe")}"'


def profile() -> dict:
    icon = resources.files("iris").joinpath("ui/assets/iris.ico")
    return {
        "profiles": [
            {
                "name": "Iris",
                "commandline": launcher(),
                "icon": str(icon),
                "tabColor": "#E9B04C",
                "colorScheme": "Iris",
                "startingDirectory": "%USERPROFILE%",
                "tabTitle": "Iris",
                "suppressApplicationTitle": True,
                "padding": "12",
            }
        ],
        "schemes": [SCHEME],
    }


def install() -> Path | None:
    path = fragment_file()
    if path is None:
        return None
    content = json.dumps(profile(), ensure_ascii=False, indent=2)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def set_title(title: str = "Iris") -> None:
    if sys.stdout.isatty():
        sys.stdout.write(f"\x1b]0;{title}\x07")
        sys.stdout.flush()
