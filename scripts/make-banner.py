#!/usr/bin/env python3
"""Render the README banner to docs/banner.jpg.

The background (docs/banner-background.png) is a picture with three empty
terminal panels. Everything written on it is drawn here, and each panel holds
the script's real output for a made-up session, rendered through the tests'
stubs as the screenshots are. Needs Pillow, a Nerd Font and Inter:

    python3 scripts/make-banner.py [--font /path/to/NerdFontMono.ttf]
"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import statusline  # noqa: E402
from tests.payloads import base  # noqa: E402
from tests.support import HOME, NOW, changed, environment, porcelain, run_main, unmerged, untracked  # noqa: E402

# The screenshots' font fallback and colour parsing, so both look alike.
_spec = importlib.util.spec_from_file_location("make_screenshots", ROOT / "scripts" / "make-screenshots.py")
shots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shots)

BACKGROUND, OUT = ROOT / "docs" / "banner-background.png", ROOT / "docs" / "banner.jpg"
SCALE = 2  # drawn at twice the background's size, for sharp text

# Measured on the background, in its own pixels: each panel's outer border,
# and the Plimsoll mark the title sits beside.
PANELS = [(152, 294, 1468, 436), (253, 469, 1570, 612), (154, 646, 1471, 787)]
LOGO = (463, 67, 611, 184)
TITLE, SUBTITLE = "Plimsoll", "How close you are to your Claude Code limits"

# A real width: at 104 columns the line sheds only the reset times, so every
# card keeps its context percentage and git symbols. Memory is turned off, as
# show_memory allows, for room.
COLUMNS = 104

# Calm, getting close, critical: (5h %, 7d %, context %, tokens used, git).
CARDS = [
    (23.5, 41.2, 18, 182_000, porcelain(changed(".M"), untracked(), ab="+2 -0")),
    (68.0, 74.5, 63, 634_000, porcelain(changed(".M"), changed(".M", "b"), changed("A."), ab="+1 -0")),
    (94.0, 88.0, 91, 912_000, porcelain(unmerged(), changed("M."))),
]


def render(five, seven, pct, used, git) -> str:
    data = base(NOW.timestamp(), cwd=f"{HOME}/code/my-project")
    data["rate_limits"]["five_hour"]["used_percentage"] = five
    data["rate_limits"]["seven_day"]["used_percentage"] = seven
    data["context_window"].update(context_window_size=1_000_000, total_input_tokens=used, used_percentage=pct)
    with (
        environment(icons=True, colour=True, max_lines=1, git=git, repo="my-project"),
        mock.patch.dict(statusline.CONFIG, {"show_memory": False}),
    ):
        return run_main(data, columns=COLUMNS)


def font_file(pattern: str) -> str:
    return subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout


def line_width(line: str, fonts) -> float:
    return sum(fonts.for_char(ch).getlength(ch) for text, _ in shots.runs(line) for ch in text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", help="a Nerd Font Mono .ttf (default: JetBrainsMono via fc-match)")
    mono = parser.parse_args().font or shots.default_font()
    if "Nerd" not in mono:
        sys.exit(f"no Nerd Font found (got {mono!r}); pass one with --font")
    title_font, body_font = font_file("Inter:style=SemiBold"), font_file("Inter:style=Regular")
    if "Inter" not in title_font:
        sys.exit("Inter not found; install it for the title")

    img = Image.open(BACKGROUND).convert("RGB")
    img = img.resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)
    pen = ImageDraw.Draw(img)

    # Title and subtitle, left-aligned beside the mark, centred on it together.
    x = (LOGO[2] + 40) * SCALE
    mid = (LOGO[1] + LOGO[3]) / 2 * SCALE
    pen.text((x, mid - 4 * SCALE), TITLE, font=ImageFont.truetype(title_font, 58 * SCALE), fill="#f4f4f8", anchor="ls")
    pen.text((x, mid + 38 * SCALE), SUBTITLE, font=ImageFont.truetype(body_font, 27 * SCALE), fill="#a9b1c6", anchor="ls")

    # One size for all three lines: the largest at which the widest fits.
    lines = [render(*card) for card in CARDS]
    inner = min(right - left for left, _, right, _ in PANELS) * SCALE - 2 * 36 * SCALE
    size = 30 * SCALE
    while True:
        fonts = shots.Fonts(mono, size)
        if size <= 8 or max(line_width(line, fonts) for line in lines) <= inner:
            break
        size -= 1

    for (left, top, right, bottom), line in zip(PANELS, lines):
        # Centred across the panel, a little below its middle, clear of the dots.
        width = line_width(line, fonts)
        x = (left + right) / 2 * SCALE - width / 2
        y = (top + (bottom - top) * 0.58) * SCALE
        for text, colour in shots.runs(line):
            for ch in text:
                font = fonts.for_char(ch)
                pen.text((x, y), ch, font=font, fill=colour, anchor="lm")
                x += font.getlength(ch)

    # JPEG: the gradients and glows make a PNG over three times the size, and
    # at this quality the text stays clean.
    img.save(OUT, quality=90, optimize=True, progressive=True, subsampling=0)
    print(f"wrote {OUT.relative_to(ROOT)} ({img.width}×{img.height}, text at {size / SCALE:.0f}px)")


if __name__ == "__main__":
    main()
