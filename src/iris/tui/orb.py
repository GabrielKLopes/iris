from __future__ import annotations

import math

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

DOT_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
SHADES = [Style(color=c) for c in ("#4a3a22", "#7a5c2c", "#b5843a", "#e9b04c", "#ffd98a")]


def _random(seed: int):
    value = seed

    def next_value() -> float:
        nonlocal value
        value = (value * 1664525 + 1013904223) % 4294967296
        return value / 4294967296

    return next_value


def _rotate(x: float, y: float, z: float, yaw: float, pitch: float) -> tuple[float, float, float]:
    x2 = x * math.cos(yaw) + z * math.sin(yaw)
    z2 = -x * math.sin(yaw) + z * math.cos(yaw)
    return x2, y * math.cos(pitch) - z2 * math.sin(pitch), y * math.sin(pitch) + z2 * math.cos(pitch)


class BrailleOrb(Widget):
    DEFAULT_CSS = "BrailleOrb { width: auto; height: auto; }"
    energy = reactive(0.0)

    def __init__(self, columns: int = 32, rows: int = 12, density: int = 380, seed: int = 7, **kwargs):
        super().__init__(**kwargs)
        self.columns = columns
        self.rows = rows
        self.time = seed * 0.37
        rand = _random(seed)
        self.strands = []
        for _ in range(density):
            radius = 0.88 + rand() * 0.13 if rand() < 0.66 else 0.32 + rand() * 0.52
            self.strands.append((radius, math.asin(rand() * 2 - 1), rand() * math.tau, 0.04 + rand() * rand() * 0.3, 0.35 + rand() * 0.65))
        self.rings = [(0.55 + rand() * 0.45, (rand() - 0.5) * math.pi, (rand() - 0.5) * math.pi, rand() * 6, math.pi * (0.5 + rand() * 1.2), (rand() - 0.5) * 0.6) for _ in range(5)]

    def get_content_width(self, container, viewport) -> int:
        return self.columns

    def get_content_height(self, container, viewport, width) -> int:
        return self.rows

    def on_mount(self) -> None:
        self.set_interval(1 / 14, self.tick)

    def tick(self) -> None:
        self.time += 0.03 + self.energy * 0.05
        self.refresh()

    def render(self) -> Text:
        width, height = self.columns * 2, self.rows * 4
        cx, cy = width / 2, height / 2
        scale = min(width, height) * 0.42 * (1 + self.energy * 0.04)
        cells: dict[tuple[int, int], list[float]] = {}

        def plot(x: float, y: float, z: float, brightness: float) -> None:
            k = 3 / (3 - z)
            px, py = int(cx + x * scale * k), int(cy - y * scale * k)
            if 0 <= px < width and 0 <= py < height:
                cell = cells.setdefault((px // 2, py // 4), [0, 0.0])
                cell[0] |= DOT_BITS[py % 4][px % 2]
                cell[1] = max(cell[1], brightness * (0.25 + (z + 1.1) / 2.2 * 0.75))

        yaw, pitch = self.time, 0.35
        for radius, lat, lon, length, glow in self.strands:
            for step in (0.0, 0.5, 1.0):
                angle = lon + length * step
                x, y, z = _rotate(radius * math.cos(lat) * math.sin(angle), radius * math.sin(lat), radius * math.cos(lat) * math.cos(angle), yaw, pitch)
                plot(x, y, z, glow)
        for radius, tx, tz, start, span, speed in self.rings:
            for i in range(0, 40):
                angle = start + self.time * speed * 4 + span * i / 40
                x, y, z = math.cos(angle) * radius, 0.0, math.sin(angle) * radius
                x, y, z = _rotate(x, y, z, tz, tx)
                x, y, z = _rotate(x, y, z, yaw * 0.6, pitch)
                plot(x, y, z, 0.55 + self.energy * 0.3)

        text = Text(no_wrap=True, overflow="crop")
        for row in range(self.rows):
            for column in range(self.columns):
                cell = cells.get((column, row))
                if cell is None:
                    text.append(" ")
                else:
                    shade = SHADES[min(len(SHADES) - 1, int(cell[1] * len(SHADES)))]
                    text.append(chr(0x2800 + cell[0]), shade)
            if row < self.rows - 1:
                text.append("\n")
        return text
