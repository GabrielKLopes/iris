from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "source"
SITE = ROOT.parent / "iris-site"


def tile(size: int) -> Image.Image:
    source = SOURCE / ("tile-small.png" if size <= 64 else "tile-1024.png")
    return Image.open(source).convert("RGBA").resize((size, size), Image.LANCZOS)


def main() -> None:
    targets = [ROOT / "assets", ROOT / "src" / "iris" / "ui" / "assets"]
    for folder in targets:
        tile(512).save(folder / "iris.png")
        tile(32).save(folder / "favicon-32.png")
        tile(180).save(folder / "apple-touch-icon.png")
        tile(256).save(folder / "iris.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    tile(1024).save(ROOT / "docs" / "images" / "logo.png")
    if SITE.exists():
        tile(256).save(SITE / "public" / "iris.png")
        tile(64).save(SITE / "src" / "app" / "icon.png")
        tile(180).save(SITE / "src" / "app" / "apple-icon.png")
    print("icons written")


if __name__ == "__main__":
    main()
