"""Shared test helpers: a frozen clock, canned git output, and running main()
in-process against a payload."""

from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta
from unittest import mock

import statusline

# A Wednesday at noon: far enough from midnight that +2h stays the same day.
NOW = datetime(2026, 10, 28, 12, 0)
HOME = "/home/tester"
ANSI = re.compile(r"\033\[[0-9;]*m")


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(NOW.timestamp(), tz)


def epoch(**delta) -> float:
    """NOW shifted by `delta` (timedelta keywords), as epoch seconds."""
    return (NOW + timedelta(**delta)).timestamp()


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def porcelain(*entries: str, head: str = "main", oid: str = "abc1234def5678", ab: str | None = None) -> str:
    """`git status --porcelain=v2 --branch` output with the given entry lines."""
    lines = [f"# branch.oid {oid}", f"# branch.head {head}"]
    if ab is not None:
        lines += ["# branch.upstream origin/main", f"# branch.ab {ab}"]
    return "\n".join(lines + list(entries)) + "\n"


def changed(xy: str, name: str = "file") -> str:
    """A type-1 (ordinary changed) entry with index/worktree status `xy`."""
    z = "0" * 40
    return f"1 {xy} N... 100644 100644 100644 {z} {z} {name}"


def renamed(xy: str = "R.", name: str = "new") -> str:
    z = "0" * 40
    return f"2 {xy} N... 100644 100644 100644 {z} {z} R100 {name}\told"


def unmerged(name: str = "file") -> str:
    z = "0" * 40
    return f"u UU N... 100644 100644 100644 100644 {z} {z} {z} {name}"


def untracked(name: str = "new") -> str:
    return f"? {name}"


def environment(
    *,
    icons: bool = False,
    colour: bool = False,
    git: str | None = None,
    repo: str | None = "repo",
    account: str | None = None,
    memory: tuple[int, int] | None = None,
    max_lines: int = 1,
) -> ExitStack:
    """Patch everything a render depends on outside its payload: the clock,
    HOME, NO_COLOR, the icons and line switches, git, the logged-in account
    and memory. One line by default, the layout most tests describe."""
    stack = ExitStack()
    stack.enter_context(mock.patch.object(statusline, "datetime", FrozenDateTime))
    env = {"HOME": HOME}
    if not colour:
        env["NO_COLOR"] = "1"
    stack.enter_context(mock.patch.dict(os.environ, env))
    if colour:
        os.environ.pop("NO_COLOR", None)  # restored by patch.dict on exit
    os.environ.pop("STATUSLINE_ICONS", None)  # the icons switch decides
    os.environ.pop("STATUSLINE_ACCOUNT", None)
    stack.enter_context(
        mock.patch.dict(statusline.CONFIG, {"icons": icons, "colour": colour, "max_lines": max_lines})
    )
    stack.enter_context(mock.patch.object(statusline, "git_status", return_value=git))
    stack.enter_context(mock.patch.object(statusline, "repo_name", return_value=repo))
    # No git dir: no operation or stash, unless a test supplies one.
    stack.enter_context(mock.patch.object(statusline, "git_dirs", return_value=None))
    stack.enter_context(mock.patch.object(statusline, "account_email", return_value=account))
    stack.enter_context(mock.patch.object(statusline, "memory_reading", return_value=memory))
    return stack


def run_main(data, columns: int = 300) -> str:
    """What the script prints for `data` on stdin at `columns` wide."""
    raw = data if isinstance(data, str) else json.dumps(data)
    out = io.StringIO()
    with (
        mock.patch.object(sys, "stdin", io.StringIO(raw)),
        mock.patch.dict(os.environ, {"COLUMNS": str(columns)}),
        redirect_stdout(out),
    ):
        statusline.main()
    return out.getvalue().rstrip("\n")
