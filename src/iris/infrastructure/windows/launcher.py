import ctypes
import subprocess
from pathlib import Path

SW_RESTORE = 9


class WindowsAppLauncher:
    def __init__(self, executable: Path, window_title_prefix: str = "Iris"):
        self.executable = executable
        self.window_title_prefix = window_title_prefix

    def open_or_focus(self) -> None:
        handle = self._find_window()
        if handle:
            user32 = ctypes.windll.user32
            user32.ShowWindow(handle, SW_RESTORE)
            user32.SetForegroundWindow(handle)
            return
        if not self.executable.exists():
            raise FileNotFoundError(f"App executable not found: {self.executable}")
        subprocess.Popen([str(self.executable), "--listen"], cwd=str(self.executable.parent))

    def _find_window(self) -> int:
        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def visit(handle, _):
            length = user32.GetWindowTextLengthW(handle)
            if length and user32.IsWindowVisible(handle):
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(handle, buffer, length + 1)
                if buffer.value.startswith(self.window_title_prefix):
                    found.append(handle)
                    return False
            return True

        user32.EnumWindows(visit, 0)
        return found[0] if found else 0
