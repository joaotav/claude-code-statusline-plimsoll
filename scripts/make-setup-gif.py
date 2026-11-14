#!/usr/bin/env python3
"""Record the setup screen to docs/setup.gif.

Runs scripts/setup.py in tmux under the tests' stubs, as the screenshots
do, so the clock is frozen and the directory, repository, account and
memory are made up. It presses a fixed run of keys and draws each screen.
Needs tmux, Pillow and a Nerd Font:

    python3 scripts/make-setup-gif.py [--font /path/to/NerdFontMono.ttf]
"""

import argparse
import importlib.util
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shots = load("make_screenshots", "make-screenshots.py")

OUT = ROOT / "docs" / "setup.gif"
SESSION = "plimsoll-setup-gif"
COLUMNS, ROWS = 92, 30
FONT_SIZE = 21
LINE = int(FONT_SIZE * 1.5)
PAD = 18
DIM = "#5c6370"

# (keys, the label shown while they're pressed, ms to hold the last screen).
# The fields start in the usual order: Memory is the 13th row, and Git the
# 14th row but the 9th field, so 8 moves take it to the top.
DOWN = "Down"
STEPS = [
    ([], None, 2200),
    ([DOWN] * 12, "down", 500),
    (["Space"], "space", 1400),
    ([DOWN], "down", 400),
    (["S-Up"] * 8, "shift + up", 1600),
    ([DOWN] * 16, "down", 500),
    (["Space"], "space", 1600),
    (["Space"], "space", 1000),
    ([DOWN] * 2, "down", 500),
    (["["] * 4, "[", 1400),
    (["Right"], "right", 1800),
    (["]"] * 4, "]", 2400),
]


def screen() -> None:
    """The setup screen under the stubs; runs inside tmux."""
    from tests.support import HOME, NOW, changed, environment, porcelain, untracked

    setup = load("setup_screen", "setup.py")
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    git = porcelain(changed(".M"), untracked(), ab="+2 -0")
    with ExitStack() as stack:
        stack.enter_context(
            environment(
                icons=True,
                colour=True,
                git=git,
                repo="my-project",
                account="me@example.com",
                memory=(int(7.6 * 2**30), int(14.8 * 2**30)),
                max_lines=2,
            )
        )
        stack.enter_context(mock.patch("os.getcwd", return_value=f"{HOME}/code/my-project"))
        stack.enter_context(mock.patch("time.time", return_value=NOW.timestamp()))
        setup.main()


def tmux(*args: str) -> str:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=True).stdout


def changed_screen(before: str) -> str:
    """The pane once it differs from `before`; a key that changes nothing
    gives up after a second."""
    deadline = time.monotonic() + 1
    while True:
        now = tmux("capture-pane", "-e", "-p", "-t", SESSION)
        if (now != before and "Preview" in now) or time.monotonic() > deadline:
            return now
        time.sleep(0.02)


def record() -> list[tuple[str, str | None, int]]:
    """(screen, label, ms) for each key pressed."""
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --screen"
    tmux("new-session", "-d", "-s", SESSION, "-x", str(COLUMNS), "-y", str(ROWS), "-c", str(ROOT), command)
    frames, current = [], ""
    try:
        for keys, label, hold in STEPS:
            if not keys:
                current = changed_screen(current)
                frames.append((current, label, hold))
            for i, key in enumerate(keys):
                tmux("send-keys", "-t", SESSION, key)
                current = changed_screen(current)
                frames.append((current, label, hold if i == len(keys) - 1 else 90))
    finally:
        subprocess.run(["tmux", "kill-session", "-t", SESSION], capture_output=True)
    return frames


class Pen:
    """Draws tmux's captured screen, colour codes and all, cell by cell."""

    def __init__(self, font_path: str):
        self.fonts = shots.Fonts(font_path, FONT_SIZE)
        bold = font_path.replace("Regular", "Bold")
        self.bold = shots.Fonts(bold, FONT_SIZE) if bold != font_path and Path(bold).exists() else self.fonts
        self.cell = self.fonts.main.getlength("M")
        self.size = (int(self.cell * COLUMNS) + 2 * PAD, LINE * ROWS + 2 * PAD)

    def draw(self, text: str, label: str | None) -> Image.Image:
        img = Image.new("RGB", self.size, shots.BG)
        pen = ImageDraw.Draw(img)
        for row, line in enumerate(text.split("\n")[:ROWS]):
            style = {"fg": None, "bold": False, "dim": False, "reverse": False}
            col = 0
            for piece in re.split(r"(\033\[[0-9;]*m)", line):
                code = re.fullmatch(r"\033\[([0-9;]*)m", piece)
                if code:
                    self.apply(style, code.group(1))
                    continue
                for ch in piece:
                    self.cell_at(pen, row, col, ch, style)
                    col += 1
        if label:
            self.key(pen, label)
        return img

    @staticmethod
    def apply(style: dict, codes: str) -> None:
        for code in (codes or "0").split(";"):
            if code in ("", "0"):
                style.update(fg=None, bold=False, dim=False, reverse=False)
            elif code == "1":
                style["bold"] = True
            elif code == "2":
                style["dim"] = True
            elif code == "7":
                style["reverse"] = True
            elif code == "22":
                style.update(bold=False, dim=False)
            elif code == "27":
                style["reverse"] = False
            elif code == "39":
                style["fg"] = None
            elif code in shots.SGR:
                style["fg"] = shots.SGR[code]

    def cell_at(self, pen, row: int, col: int, ch: str, style: dict) -> None:
        fg = style["fg"] or (DIM if style["dim"] else shots.FG)
        bg = None
        if style["reverse"]:
            fg, bg = shots.BG, fg
        x, y = PAD + col * self.cell, PAD + row * LINE
        if bg:
            pen.rectangle((x, y, x + self.cell, y + LINE), fill=bg)
        if ch != " ":
            fonts = self.bold if style["bold"] else self.fonts
            pen.text((x, y + LINE / 2), ch, font=fonts.for_char(ch), fill=fg, anchor="lm")

    def key(self, pen, label: str) -> None:
        """The key being pressed, in the bottom right corner."""
        font = self.bold.main
        width = font.getlength(label) + 2 * FONT_SIZE * 0.6
        right, bottom = self.size[0] - PAD, self.size[1] - PAD
        box = (right - width, bottom - LINE * 1.3, right, bottom)
        pen.rounded_rectangle(box, radius=8, fill="#3e4451", outline=shots.SGR["36"], width=2)
        pen.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label, font=font, fill=shots.FG, anchor="mm")


def save(images: list[Image.Image], durations: list[int]) -> None:
    # One palette from every frame, so colours stay true and don't flicker:
    # each frame lends a different band of itself to the sample.
    strip = images[0].height // 8
    sample = Image.new("RGB", (images[0].width, strip * len(images)))
    for i, img in enumerate(images):
        top = i % 8 * strip
        sample.paste(img.crop((0, top, img.width, top + strip)), (0, i * strip))
    palette = sample.quantize(colors=256)
    frames = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img in images]
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", help="a Nerd Font Mono .ttf (default: JetBrainsMono via fc-match)")
    parser.add_argument("--screen", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.screen:
        return screen()
    font_path = args.font or shots.default_font()
    if "Nerd" not in font_path:
        sys.exit(f"no Nerd Font found (got {font_path!r}); pass one with --font")

    pen = Pen(font_path)
    frames = record()
    save([pen.draw(text, label) for text, label, _ in frames], [ms for _, _, ms in frames])
    print(f"wrote {OUT.relative_to(ROOT)}, {len(frames)} frames, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
