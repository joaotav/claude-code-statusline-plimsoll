#!/usr/bin/env python3
"""Point Claude Code's status line at this script.

Adds the statusLine block to settings.json and leaves every other setting as
it was. The old file is backed up first, and a second run changes nothing:

    python3 scripts/install.py

--uninstall takes the block out again, and offers to delete the status
line's own settings file. With CLAUDE_CONFIG_DIR set, both use that folder.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "statusline.py"
sys.path.insert(0, str(SCRIPT.parent))

from statusline import CONFIG_FILE  # noqa: E402


def settings_path() -> Path:
    # Each config folder has its own settings.json, as it has its own
    # .claude.json.
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(config_dir) if config_dir else Path.home() / ".claude") / "settings.json"


def status_line() -> dict:
    return {"type": "command", "command": str(SCRIPT), "padding": 0, "refreshInterval": 60}


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def load(path: Path) -> tuple[dict, str | None]:
    """The settings at `path` and the file's text, None when there's no file.
    Exits on a file that isn't a JSON object."""
    if not path.exists():
        return {}, None
    text = path.read_text(encoding="utf-8")
    try:
        settings = json.loads(text) if text.strip() else {}
    except ValueError as e:
        sys.exit(f"{path} isn't valid JSON ({e}). Fix it, or edit the block by hand.")
    if not isinstance(settings, dict):
        sys.exit(f"{path} doesn't hold a JSON object. Fix it, or edit the block by hand.")
    return settings, text


def save(path: Path, settings: dict, text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        backup = path.with_name(f"{path.name}.bak.{int(time.time())}")
        shutil.copy2(path, backup)
        print(f"Backed up the old settings to {backup}.")
    # Written beside it and renamed over it, so a crash can't leave it half-written.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if text is not None:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def install(path: Path, ask=confirm) -> bool:
    """Write the block into the settings at `path`. False when the person
    declines to replace a status line already there."""
    # A settings.json linked from a dotfiles repo stays a link: write its target.
    path = path.resolve()
    settings, text = load(path)
    new = status_line()
    old = settings.get("statusLine")
    if old == new:
        print(f"{path} already uses {SCRIPT}.")
        return True
    if old is not None:
        print(f"{path} already has a status line:\n{json.dumps(old, indent=2)}")
        if not ask("Replace it?"):
            print("Left it unchanged.")
            return False

    settings["statusLine"] = new
    save(path, settings, text)
    print(f"Added the status line to {path}.")
    return True


def uninstall(path: Path, ask=confirm) -> bool:
    """Take the block out of the settings at `path` when it runs this script,
    then offer to delete the status line's settings file beside it. False
    when a different status line is left in place."""
    # The settings file sits in the config folder, even when settings.json
    # is a link to somewhere else.
    ours = path.parent / CONFIG_FILE
    path = path.resolve()
    settings, text = load(path)
    old = settings.get("statusLine")
    gone = True
    if old is None:
        print(f"{path} has no status line to remove.")
    elif not isinstance(old, dict) or old.get("command") != str(SCRIPT):
        print(f"{path} runs a different status line, so it was left alone:\n{json.dumps(old, indent=2)}")
        gone = False
    else:
        del settings["statusLine"]
        save(path, settings, text)
        print(f"Removed the status line from {path}.")

    # Only this folder's file: one in ~/.claude may serve other accounts too.
    if ours.is_file() and ask(f"Delete the status line's settings in {ours} too?"):
        ours.unlink()
        print(f"Deleted {ours}.")
    return gone


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Point Claude Code's status line at this script.")
    parser.add_argument("--uninstall", action="store_true", help="remove it again")
    args = parser.parse_args()
    done = (uninstall if args.uninstall else install)(settings_path())
    sys.exit(0 if done else 1)
