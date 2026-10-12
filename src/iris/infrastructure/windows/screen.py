import base64
import ctypes
import io
import json
import re
import time

import anthropic
import mss
from PIL import Image

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MAX_WIDTH = 1366


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def active_app_center() -> tuple[int, int] | None:
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(handle, _):
        if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        if buffer.value in ("Iris", "Program Manager"):
            return True
        rect = RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        if rect.right - rect.left < 300 or rect.bottom - rect.top < 200:
            return True
        found.append(((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
        return False

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


class ScreenVision:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def capture(self, monitor: int | None = None) -> tuple[bytes, dict, float]:
        with mss.MSS() as screens:
            monitors = screens.monitors[1:]
            if monitor and 1 <= monitor <= len(monitors):
                area = monitors[monitor - 1]
            else:
                center = active_app_center()
                area = next(
                    (m for m in monitors if center and m["left"] <= center[0] < m["left"] + m["width"] and m["top"] <= center[1] < m["top"] + m["height"]),
                    monitors[0],
                )
            shot = screens.grab(area)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        scale = min(1.0, MAX_WIDTH / image.width)
        if scale < 1.0:
            image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return buffer.getvalue(), area, scale

    def _ask(self, jpeg: bytes, prompt: str, max_tokens: int = 400) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()

    def describe(self, question: str, monitor: int | None = None) -> str:
        jpeg, _, _ = self.capture(monitor)
        return self._ask(
            jpeg,
            f"This is a screenshot of the user's screen. {question}\n"
            "Answer in Brazilian Portuguese, briefly. Mention visible links, buttons, video titles or text that matter.",
        )

    def click(self, target: str, monitor: int | None = None) -> str:
        jpeg, area, scale = self.capture(monitor)
        width, height = int(area["width"] * scale), int(area["height"] * scale)
        answer = self._ask(
            jpeg,
            f"The screenshot is {width}x{height} pixels. Find this element: {target}\n"
            'Reply only with JSON: {"x": <int>, "y": <int>, "label": "<what you found>"} for the center of the element, '
            'or {"x": null, "label": "<why>"} if it is not visible.',
            max_tokens=150,
        )
        match = re.search(r"\{.*\}", answer, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        if data.get("x") is None:
            return f"Could not find '{target}' on the screen: {data.get('label', answer)}"
        x = area["left"] + int(data["x"] / scale)
        y = area["top"] + int(data["y"] / scale)
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return f"Clicked '{data.get('label', target)}' at ({x}, {y})"
