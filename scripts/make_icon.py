import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
GOLD = (244, 182, 66)
LIGHT = (255, 226, 150)
DEEP = (190, 120, 30)
OUT = Path(__file__).resolve().parents[1] / "assets"


def ring(draw: ImageDraw.ImageDraw, center: float, radius: float, tilt: float, rotation: float, width: int, color, start=0, end=360):
    points = []
    for step in range(start, end + 1, 2):
        angle = math.radians(step)
        x, y = math.cos(angle) * radius, math.sin(angle) * radius * tilt
        rx = x * math.cos(rotation) - y * math.sin(rotation)
        ry = x * math.sin(rotation) + y * math.cos(rotation)
        points.append((center + rx, center + ry))
    draw.line(points, fill=color, width=width, joint="curve")


def render() -> Image.Image:
    c = SIZE / 2
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for i in range(60, 0, -1):
        r = c * 0.9 * i / 60
        alpha = int(70 * (1 - i / 60) ** 1.6)
        g.ellipse([c - r, c - r, c + r, c + r], fill=(*GOLD, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(SIZE * 0.02))

    art = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    ring(d, c, c * 0.78, 1.0, 0, int(SIZE * 0.022), (*GOLD, 235))
    ring(d, c, c * 0.74, 0.32, math.radians(-24), int(SIZE * 0.026), (*LIGHT, 255))
    ring(d, c, c * 0.66, 0.42, math.radians(38), int(SIZE * 0.018), (*GOLD, 220), 200, 520)
    ring(d, c, c * 0.52, 0.95, math.radians(70), int(SIZE * 0.012), (*DEEP, 200), 20, 250)

    rng = random.Random(7)
    for _ in range(46):
        angle = rng.uniform(0, math.tau)
        dist = c * rng.uniform(0.35, 0.8)
        x, y = c + math.cos(angle) * dist, c + math.sin(angle) * dist * rng.uniform(0.6, 1.0)
        length = SIZE * rng.uniform(0.012, 0.04)
        d.line([(x, y), (x + length * math.cos(angle + 1.57), y + length * math.sin(angle + 1.57))], fill=(*LIGHT, rng.randint(140, 230)), width=int(SIZE * 0.008))

    for i in range(40, 0, -1):
        r = c * 0.24 * i / 40
        t = 1 - i / 40
        color = tuple(int(GOLD[k] + (255 - GOLD[k]) * t) for k in range(3))
        d.ellipse([c - r, c - r, c + r, c + r], fill=(*color, 255))
    return Image.alpha_composite(glow, art)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    icon = render()
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "iris.png")
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "iris.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    icon.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
