#!/usr/bin/env python3
"""Render the README banner to docs/banner.jpg.

The background (docs/banner-background.png) is a picture with three empty
terminal panels. Everything written on it is drawn here, and each panel holds
the script's real output for a made-up session, rendered through the tests'
stubs as the screenshots are. Needs Pillow, a Nerd Font, Space Grotesk and
Inter:

    python3 scripts/make-banner.py [--font /path/to/NerdFontMono.ttf]
"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
PANELS = [(61, 284, 1663, 419), (86, 457, 1687, 589), (56, 627, 1663, 760)]
DOTS = 36  # how far below a panel's top its window dots end
LOGO = (385, 57, 615, 221)
TITLE, SUBTITLE = "Plimsoll", "Your Claude Code limits at a glance"

# Wide enough that no card sheds anything, reset times and memory included.
COLUMNS = 160

# Calm, getting close, critical: (5h %, 7d %, context %, tokens used, GB of
# memory used, git).
CARDS = [
    (23.5, 41.2, 18, 182_000, 7.6, porcelain(changed(".M"), untracked(), ab="+2 -0")),
    (68.0, 74.5, 63, 634_000, 10.1, porcelain(changed(".M"), changed(".M", "b"), changed("A."), ab="+1 -0")),
    (94.0, 88.0, 91, 912_000, 13.3, porcelain(unmerged(), changed("M."))),
]


def render(five, seven, pct, used, memory, git) -> str:
    data = base(NOW.timestamp(), cwd=f"{HOME}/code/my-project")
    data["rate_limits"]["five_hour"]["used_percentage"] = five
    data["rate_limits"]["seven_day"]["used_percentage"] = seven
    data["context_window"].update(context_window_size=1_000_000, total_input_tokens=used, used_percentage=pct)
    with environment(
        icons=True,
        colour=True,
        max_lines=1,
        git=git,
        repo="my-project",
        memory=(int(memory * 2**30), int(14.8 * 2**30)),
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
    title_font, body_font = font_file("Space Grotesk:style=Bold"), font_file("Inter:style=Regular")
    if "SpaceGrotesk" not in title_font:
        sys.exit("Space Grotesk not found; install it for the title")
    if "Inter" not in body_font:
        sys.exit("Inter not found; install it for the subtitle")

    img = Image.open(BACKGROUND).convert("RGB")
    img = img.resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)

    # Title and subtitle, left-aligned beside the mark, centred on it together.
    x = (LOGO[2] + 40) * SCALE
    mid = (LOGO[1] + LOGO[3]) / 2 * SCALE
    title = ImageFont.truetype(title_font, 58 * SCALE)
    try:
        title.set_variation_by_name(b"Bold")  # Google's file is a variable font
    except OSError:
        pass  # a static Bold
    subtitle = ImageFont.truetype(body_font, 27 * SCALE)
    words = [((x, mid - 4 * SCALE), TITLE, title, "#ffffff"), ((x, mid + 38 * SCALE), SUBTITLE, subtitle, "#f3f0ff")]

    # A soft dark shadow under both, so the white stands out on the light sky.
    shadow = Image.new("L", img.size, 0)
    for (wx, wy), text, font, _ in words:
        ImageDraw.Draw(shadow).text((wx, wy + 2 * SCALE), text, font=font, fill=110, anchor="ls")
    shadow = shadow.filter(ImageFilter.GaussianBlur(6 * SCALE))
    img = Image.composite(Image.new("RGB", img.size, "#1b2150"), img, shadow)
    pen = ImageDraw.Draw(img)
    for xy, text, font, colour in words:
        pen.text(xy, text, font=font, fill=colour, anchor="ls")

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
        # Centred across the panel, and in the space below the dots.
        width = line_width(line, fonts)
        x = (left + right) / 2 * SCALE - width / 2
        y = (top + DOTS + bottom) / 2 * SCALE
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
