#!/usr/bin/env python3
"""Point Claude Code's status line at this script.

Adds the statusLine block to settings.json and leaves every other setting as
it was. The old file is backed up first, and a second run changes nothing:

    python3 scripts/install.py

With CLAUDE_CONFIG_DIR set, it installs into that folder's settings.json.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "statusline.py"


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


def install(path: Path, ask=confirm) -> bool:
    """Write the block into the settings at `path`. False when the person
    declines to replace a status line already there; exits on a file that
    isn't a JSON object."""
    # A settings.json linked from a dotfiles repo stays a link: write its target.
    path = path.resolve()
    settings, text = {}, None
    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            settings = json.loads(text) if text.strip() else {}
        except ValueError as e:
            sys.exit(f"{path} isn't valid JSON ({e}). Fix it, or add the block by hand.")
        if not isinstance(settings, dict):
            sys.exit(f"{path} doesn't hold a JSON object. Fix it, or add the block by hand.")

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
    print(f"Added the status line to {path}.")
    return True


if __name__ == "__main__":
    sys.exit(0 if install(settings_path()) else 1)
