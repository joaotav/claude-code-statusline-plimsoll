#!/usr/bin/env python3
"""Pick what the status line shows, with a live preview, and save it.

Opens on the current settings, and saves only what differs from the defaults
to the settings file in Claude's config folder. Run it again whenever you
want to change something:

    python3 scripts/setup.py

The preview uses this machine's directory, git, account and memory, with a
sample session for the rest. Needs curses, which Python has on Linux and
macOS.
"""

from __future__ import annotations

import curses
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import install  # noqa: E402
import statusline  # noqa: E402

DEFAULTS = dict(statusline.CONFIG)

# A heading, or (label, key, hint). A key with a bool default toggles, and the
# others step through CHOICES. Indented fields only show with Context on.
ROWS = [
    "Fields",
    ("Directory", "show_cwd", "The session's folder, shortened when narrow"),
    ("Usage limits", "show_quota", "The 5-hour and 7-day limits, with reset times"),
    ("Cost", "show_cost", "API-key sessions only, in place of the usage limits"),
    ("Context", "show_context", "Tokens in the context window, and the share used"),
    ("  Input tokens", "show_input_tokens", "The last call's input tokens"),
    ("  Cache split", "show_cache_split", "Cache writes and reads, beside the input tokens"),
    ("  Output tokens", "show_output_tokens", "The last call's output tokens"),
    ("  Duration", "show_duration", "How long the session has run"),
    ("  Lines changed", "show_lines_changed", "Lines added and removed this session"),
    ("Cold cache", "show_cache", "When the next message would resend a big context"),
    ("Model", "show_model", "With the effort level, and a badge in fast mode"),
    ("Output style", "show_output_style", "Only when it isn't the default one"),
    ("Memory", "show_memory", "System memory in use, out of the total"),
    ("Git", "show_git", "Repository, branch and what's changed"),
    ("Agent", "show_agent", "The --agent name and worktree, when there is one"),
    ("Account", "show_account", "The logged-in email, to tell accounts apart"),
    "Look",
    ("Icons", "icons", "Nerd Font glyphs. Turn off if they draw as boxes"),
    ("Colour", "colour", "Green, yellow and red as the limits fill up"),
    ("Narrow terminal", "max_lines", "Wrap onto a second line, or drop fields"),
    ("Separator", "separator", "Goes between fields, drawn dim"),
]
FIELDS = [row for row in ROWS if not isinstance(row, str)]
KEYS = [key for _, key, _ in FIELDS]

CHOICES = {
    "max_lines": [(2, "wrap"), (1, "drop")],
    "separator": [(" • ", "•"), (" | ", "|"), (" · ", "·"), ("  ", "space")],
}

SGR_RE = re.compile(r"\033\[([0-9;]*)m")
COLOURS = {
    "31": curses.COLOR_RED,
    "32": curses.COLOR_GREEN,
    "33": curses.COLOR_YELLOW,
    "34": curses.COLOR_BLUE,
    "35": curses.COLOR_MAGENTA,
    "36": curses.COLOR_CYAN,
}


def settings_path() -> Path:
    """The file the status line reads, or where a new one goes."""
    found = statusline.config_file()
    if found is not None:
        return found
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(config_dir) if config_dir else Path.home() / ".claude") / statusline.CONFIG_FILE


def read_file(path: Path) -> dict:
    """The file's settings as they stand, to keep the keys setup doesn't
    manage. Exits on a broken file rather than write over it."""
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        sys.exit(f"{path} isn't valid JSON ({e}). Fix it or delete it, then run this again.")
    if not isinstance(settings, dict):
        sys.exit(f"{path} doesn't hold a JSON object. Fix it or delete it, then run this again.")
    return settings


def save(path: Path, current: dict, settings: dict) -> bool:
    """Write `settings` over `current`, keeping only what differs from the
    defaults. False when there was nothing to write."""
    new = dict(current)
    for key, value in settings.items():
        if value == DEFAULTS[key]:
            new.pop(key, None)
        else:
            new[key] = value
    if not path.exists() and not new:
        return False  # the defaults need no file
    # A settings file linked from a dotfiles repo stays a link: write its target.
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return True


def installed(path: Path) -> bool:
    """Whether Claude Code's settings at `path` already run this script."""
    try:
        block = json.loads(path.read_text(encoding="utf-8")).get("statusLine")
        return block.get("command") == install.status_line()["command"]
    except (OSError, ValueError, AttributeError):
        return False


def sample() -> dict:
    """A session for the preview. Directory and git come from where setup runs."""
    now, cwd = time.time(), os.getcwd()
    return {
        "cwd": cwd,
        "workspace": {"current_dir": cwd},
        "model": {"display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "output_style": {"name": "Explanatory"},
        "agent": {"name": "reviewer"},
        "cost": {"total_duration_ms": 1_380_000, "total_lines_added": 156, "total_lines_removed": 23},
        "context_window": {
            "total_input_tokens": 64000,
            "context_window_size": 200000,
            "used_percentage": 32,
            "current_usage": {
                "input_tokens": 8500,
                "output_tokens": 1200,
                "cache_creation_input_tokens": 5000,
                "cache_read_input_tokens": 2000,
            },
        },
        # Gone cold, as after a break, so the field has something to show.
        "prompt_cache": {"warm": False, "recache_tokens_if_cold": 64000},
        "rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": int(now + 2 * 3600)},
            "seven_day": {"used_percentage": 71.2, "resets_at": int(now + 4 * 86400)},
        },
    }


def preview(settings: dict, width: int) -> list[str]:
    statusline.CONFIG.update(settings)
    return statusline.render(sample(), width).split("\n")


def runs(line: str) -> list[tuple[str, str]]:
    """A rendered line as (text, SGR code in force) pieces, '0' for none."""
    pieces, code, pos = [], "0", 0
    for m in SGR_RE.finditer(line):
        if m.start() > pos:
            pieces.append((line[pos : m.start()], code))
        code, pos = m.group(1) or "0", m.end()
    if pos < len(line):
        pieces.append((line[pos:], code))
    return pieces


class Editor:
    """Which row is selected and what each setting is, apart from curses."""

    def __init__(self, settings: dict):
        self.settings = dict(settings)
        self.saved = dict(settings)
        self.choices = {}
        for key, options in CHOICES.items():
            # A value set by hand in the file stays on offer.
            if settings[key] not in [value for value, _ in options]:
                options = [(settings[key], repr(settings[key]))] + options
            self.choices[key] = options
        self.cursor = 0

    @property
    def field(self) -> tuple[str, str, str]:
        return FIELDS[self.cursor]

    @property
    def dirty(self) -> bool:
        return self.settings != self.saved

    def move(self, step: int) -> None:
        self.cursor = min(max(self.cursor + step, 0), len(FIELDS) - 1)

    def change(self, step: int) -> None:
        key = self.field[1]
        if isinstance(DEFAULTS[key], bool):
            self.settings[key] = not self.settings[key]
            return
        values = [value for value, _ in self.choices[key]]
        index = values.index(self.settings[key])
        self.settings[key] = values[(index + step) % len(values)]

    def choice(self, key: str) -> str:
        """The label of the option chosen for `key`."""
        return dict(self.choices[key])[self.settings[key]]


# Filled in by colours() once curses is up; the fallbacks need no colour.
STYLE = {"accent": 0, "on": 0, "warn": 0}
HINT_COLUMN = 34  # where the selected row's hint starts


def colours() -> None:
    STYLE.update(accent=curses.A_BOLD, on=curses.A_BOLD, warn=curses.A_BOLD)
    if not curses.has_colors():
        return
    curses.use_default_colors()
    for i, colour in enumerate(COLOURS.values(), 1):
        curses.init_pair(i, colour, -1)
    STYLE.update(
        accent=attr_for("36") | curses.A_BOLD,
        on=attr_for("32"),
        warn=attr_for("33") | curses.A_BOLD,
    )


def put(win, y: int, x: int, text: str, attr: int = 0) -> int:
    """addstr clipped to the window, returning the column after the text;
    curses raises on the last cell."""
    height, width = win.getmaxyx()
    if 0 <= y < height and x < width:
        try:
            win.addstr(y, x, text[: width - x], attr)
        except curses.error:
            pass
    return x + len(text)


def attr_for(code: str) -> int:
    if code == "2":
        return curses.A_DIM
    if code in COLOURS and curses.has_colors():
        return curses.color_pair(list(COLOURS).index(code) + 1)
    return 0


def draw_title(win, editor: Editor, path: Path) -> None:
    columns = win.getmaxyx()[1]
    x = put(win, 0, 1, "Plimsoll", STYLE["accent"])
    put(win, 0, x, " · status line setup", curses.A_DIM)
    if editor.dirty:
        status, attr = "● unsaved", STYLE["warn"]
    else:
        status, attr = str(path).replace(str(Path.home()), "~", 1), curses.A_DIM
    put(win, 0, max(columns - len(status) - 1, 30), status, attr)


def draw_preview(win, editor: Editor, width: int) -> int:
    """The line in a box `width` wide inside; returns the row below it."""
    lines = preview(editor.settings, width)
    title = f" Preview · {width} columns "
    put(win, 1, 0, "╭─" + title + "─" * max(width - len(title), 0) + "─╮", curses.A_DIM)
    # Two rows at least, so the list doesn't jump when the line wraps.
    rows = max(len(lines), 2)
    for i in range(rows):
        y = 2 + i
        put(win, y, 0, "│", curses.A_DIM)
        x = 2
        for text, code in runs(lines[i] if i < len(lines) else ""):
            x = put(win, y, x, text, attr_for(code))
        put(win, y, width + 3, "│", curses.A_DIM)
    put(win, 2 + rows, 0, "╰" + "─" * (width + 2) + "╯", curses.A_DIM)
    return 3 + rows


def draw_row(win, y: int, editor: Editor, row) -> None:
    label, key, hint = row
    selected = row == editor.field
    if selected:
        put(win, y, 0, "▌", STYLE["accent"])
    x = 2 + len(label) - len(label.lstrip())
    name = label.strip()
    if isinstance(DEFAULTS[key], bool):
        on = editor.settings[key]
        x = put(win, y, x, "● " if on else "○ ", STYLE["on"] if on else curses.A_DIM)
        put(win, y, x, name, curses.A_BOLD if selected else 0 if on else curses.A_DIM)
    else:
        put(win, y, x + 2, name, curses.A_BOLD if selected else 0)
        put(win, y, 22, f"‹ {editor.choice(key)} ›", STYLE["accent"])
    if selected:
        put(win, y, HINT_COLUMN, hint, curses.A_DIM)


def draw_keys(win, keys, x: int = 1) -> None:
    """The footer: each key highlighted, then what it does."""
    y = win.getmaxyx()[0] - 1
    for key, action in keys:
        x = put(win, y, x, f" {key} ", curses.A_REVERSE)
        x = put(win, y, x, f" {action}  ", curses.A_DIM)


def draw(win, editor: Editor, path: Path, width: int) -> None:
    win.erase()
    height, columns = win.getmaxyx()
    draw_title(win, editor, path)
    top = draw_preview(win, editor, width) + 1

    # Headings and settings; the list scrolls so the selected one stays in view.
    lines = []
    for row in ROWS:
        if isinstance(row, str):
            lines += ([None] if lines else []) + [row]
        else:
            lines.append(row)
    room = max(height - 1 - top, 1)
    at = lines.index(editor.field)
    offset = min(max(at - room + 1, 0), max(len(lines) - room, 0))
    for i, line in enumerate(lines[offset : offset + room]):
        y = top + i
        if isinstance(line, str):
            x = put(win, y, 1, line.upper() + " ", STYLE["accent"])
            put(win, y, x, "─" * (columns - x - 1), curses.A_DIM)
        elif line is not None:
            draw_row(win, y, editor, line)
    if offset > 0:
        put(win, top, columns - 2, "↑", curses.A_DIM)
    if offset + room < len(lines):
        put(win, top + room - 1, columns - 2, "↓", curses.A_DIM)

    draw_keys(win, [("↑↓", "move"), ("space", "change"), ("[ ]", "width"), ("s", "save"), ("q", "quit")])
    win.refresh()


def ask(win, question: str) -> bool:
    height, _ = win.getmaxyx()
    win.move(height - 1, 0)
    win.clrtoeol()
    x = put(win, height - 1, 1, question, STYLE["warn"])
    draw_keys(win, [("y", "yes"), ("n", "no")], x + 2)
    return win.get_wch() in ("y", "Y")


def edit(win, editor: Editor, path: Path) -> bool:
    """Run the screen until the person saves (True) or quits (False)."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    colours()
    width = None  # follows the terminal until [ or ] sets it
    while True:
        columns = win.getmaxyx()[1] - 4  # the box and its padding
        width = min(width or columns, columns)
        draw(win, editor, path, width)
        key = win.get_wch()
        if key in (curses.KEY_UP, "k"):
            editor.move(-1)
        elif key in (curses.KEY_DOWN, "j"):
            editor.move(1)
        elif key in (" ", "\n", curses.KEY_RIGHT, "l"):
            editor.change(1)
        elif key in (curses.KEY_LEFT, "h"):
            editor.change(-1)
        elif key == "[":
            width = max(width - 10, 20)
        elif key == "]":
            width = min(width + 10, columns)
        elif key == "s":
            return True
        elif key in ("q", "\033") and (not editor.dirty or ask(win, "Quit without saving?")):
            return False


def main() -> None:
    path = settings_path()
    current = read_file(path)
    statusline.load_settings()
    editor = Editor({key: statusline.CONFIG[key] for key in KEYS})
    os.environ.setdefault("ESCDELAY", "25")  # Esc quits without a second's wait
    if not curses.wrapper(edit, editor, path):
        print("Left the settings unchanged.")
        return
    if save(path, current, editor.settings):
        print(f"Saved to {path}.")
    else:
        print("These are the defaults, so no settings file is needed.")

    claude_settings = install.settings_path()
    if not installed(claude_settings) and install.confirm(f"Point Claude Code at the status line in {claude_settings} too?"):
        install.install(claude_settings)


if __name__ == "__main__":
    main()
