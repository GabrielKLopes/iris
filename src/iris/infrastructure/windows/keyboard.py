import ctypes
import time

from iris.application.intent import normalize

user32 = ctypes.windll.user32

KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_TAB = 0x09
VK_W = 0x57
MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}
BROWSER_SUFFIXES = (" - Google Chrome", " - Microsoft​ Edge", " - Microsoft Edge", " — Mozilla Firefox", " - Brave")


def press(*keys: int) -> None:
    for key in keys:
        user32.keybd_event(key, 0, 0, 0)
    for key in reversed(keys):
        user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)


def window_title(handle: int) -> str:
    length = user32.GetWindowTextLengthW(handle)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value


def find_browser_window() -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(handle, _):
        if user32.IsWindowVisible(handle) and window_title(handle).endswith(BROWSER_SUFFIXES):
            found.append(handle)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def active_window_title() -> str:
    found: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(handle, _):
        if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
            return True
        title = window_title(handle)
        if not title or title in ("Iris", "Program Manager"):
            return True
        found.append(title)
        return False

    user32.EnumWindows(visit, 0)
    return found[0] if found else ""


def focus(handle: int) -> None:
    press(VK_MENU)
    user32.ShowWindow(handle, 9)
    user32.SetForegroundWindow(handle)
    time.sleep(0.2)


def tab_title(handle: int) -> str:
    title = window_title(handle)
    for suffix in BROWSER_SUFFIXES:
        title = title.removesuffix(suffix)
    return title


class WindowsDesktopKeys:
    def media(self, action: str) -> str:
        key = MEDIA_KEYS.get(action)
        if key is None:
            return f"Unknown media action: {action}"
        repeat = 5 if action in ("volume_up", "volume_down") else 1
        for _ in range(repeat):
            press(key)
        return f"Sent {action}"

    def close_tab(self, match: str | None = None) -> str:
        browser = find_browser_window()
        if not browser:
            return "No browser window is open"
        focus(browser)
        if match:
            wanted = normalize(match)
            seen = []
            for _ in range(40):
                title = tab_title(browser)
                if wanted in normalize(title):
                    press(VK_CONTROL, VK_W)
                    return f"Closed the tab '{title}'"
                if title in seen:
                    break
                seen.append(title)
                press(VK_CONTROL, VK_TAB)
                time.sleep(0.15)
            return f"No tab matching '{match}'. Open tabs: {', '.join(seen)}"
        title = tab_title(browser)
        press(VK_CONTROL, VK_W)
        return f"Closed the current tab '{title}'"
