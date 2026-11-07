#!/usr/bin/env python3
"""Render the README screenshots to docs/*.png.

Uses the tests' stubs, so the clock is frozen and the directory, repository,
account and memory are made up; nothing from this machine is shown. Needs
Pillow and a Nerd Font, which the status line itself does not:

    python3 scripts/make-screenshots.py [--font /path/to/NerdFontMono.ttf]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.payloads import base  # noqa: E402
from tests.support import HOME, NOW, changed, environment, porcelain, run_main, untracked  # noqa: E402

OUT = ROOT / "docs"
SCALE = 2  # drawn at twice the size, for high-density screens
FONT_SIZE, PAD = 14 * SCALE, 12 * SCALE

# One Dark, a common terminal theme.
BG, FG = "#282c34", "#abb2bf"
SGR = {
    "31": "#e06c75",
    "32": "#98c379",
    "33": "#e5c07b",
    "34": "#61afef",
    "35": "#c678dd",
    "36": "#56b6c2",
    "2": "#5c6370",
}

# (file, icons, columns): full width, with icons and without.
SHOTS = [
    ("statusline-icons.png", True, 300),
    ("statusline-plain.png", False, 300),
]


def render(icons: bool, columns: int) -> str:
    data = base(NOW.timestamp(), cwd=f"{HOME}/code/work/my-project")
    with environment(
        icons=icons,
        colour=True,
        git=porcelain(changed(".M"), untracked(), ab="+2 -0"),
        repo="my-project",
        account="me@example.com",
        memory=(int(7.6 * 2**30), int(14.8 * 2**30)),
    ):
        return run_main(data, columns=columns)


def runs(line: str):
    """(text, colour) pieces of a line with SGR colour codes."""
    colour = FG
    for piece in re.split(r"(\033\[[0-9;]*m)", line):
        code = re.fullmatch(r"\033\[([0-9;]*)m", piece)
        if code:
            colour = SGR.get(code.group(1), FG)
        elif piece:
            yield piece, colour


class Fonts:
    """The Nerd Font, falling back per character to whichever installed font
    fontconfig picks for it, as a terminal does (the font lacks ⇡ and ⇣)."""

    def __init__(self, path: str, size: int = FONT_SIZE):
        self.size = size
        self.main = ImageFont.truetype(path, size)
        out = subprocess.run(["fc-query", "-f", "%{charset}", path], capture_output=True, text=True).stdout
        self.ranges = [[int(n, 16) for n in r.split("-")] for r in out.split()]
        self.fallbacks: dict[str, ImageFont.FreeTypeFont] = {}

    def for_char(self, ch: str) -> ImageFont.FreeTypeFont:
        if any(r[0] <= ord(ch) <= r[-1] for r in self.ranges):
            return self.main
        if ch not in self.fallbacks:
            path = subprocess.run(
                ["fc-match", "-f", "%{file}", f"monospace:charset={ord(ch):x}"], capture_output=True, text=True
            ).stdout
            self.fallbacks[ch] = ImageFont.truetype(path, self.size)
        return self.fallbacks[ch]


def draw(line: str, fonts: Fonts, path: Path) -> None:
    pieces = [(ch, colour, fonts.for_char(ch)) for text, colour in runs(line) for ch in text]
    height = int(FONT_SIZE * 1.6)
    width = sum(font.getlength(ch) for ch, _, font in pieces)
    img = Image.new("RGB", (int(width) + 2 * PAD, height + 2 * PAD), BG)
    pen = ImageDraw.Draw(img)
    x = PAD
    for ch, colour, font in pieces:
        pen.text((x, PAD + height / 2), ch, font=font, fill=colour, anchor="lm")
        x += font.getlength(ch)
    img.save(path, optimize=True)


def default_font() -> str:
    out = subprocess.run(
        ["fc-match", "-f", "%{file}", "JetBrainsMono Nerd Font Mono"], capture_output=True, text=True
    )
    return out.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", help="a Nerd Font Mono .ttf (default: JetBrainsMono via fc-match)")
    font_path = parser.parse_args().font or default_font()
    if "Nerd" not in font_path:
        sys.exit(f"no Nerd Font found (got {font_path!r}); pass one with --font")
    fonts = Fonts(font_path)

    OUT.mkdir(exist_ok=True)
    for name, icons, columns in SHOTS:
        draw(render(icons, columns), fonts, OUT / name)
        print(f"wrote {(OUT / name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
