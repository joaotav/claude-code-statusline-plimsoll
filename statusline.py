#!/usr/bin/env python3
"""Claude Code statusline: subscription usage at a glance.

Reads the statusline JSON payload on stdin and prints one row (text labels
shown; with `icons` on they become Nerd Font glyphs):

    ~/…/my-project | 5h 23.5% [19:45] | 7d 41.2% [Thu 14:00] |
    476.5k/1M 48% | Opus 5.5 (high) | my-project:main !2 +1 ?1 ⇡2

Quota data comes straight from stdin (`rate_limits`), so this makes no network
calls and reads no credentials. The only subprocess is one `git status`.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

CONFIG = {
    # Segments, in display order.
    "show_cwd": True,
    "show_quota": True,
    # The session's cost, with an API key only: on a subscription it is an
    # API-price estimate, not a bill.
    "show_cost": True,
    "show_context": True,
    "show_model": True,
    # The output style, unless it's the default one.
    "show_output_style": True,
    "show_git": True,
    # The logged-in account's email, to tell accounts apart. Reads that one
    # field from the active config dir's .claude.json. STATUSLINE_ACCOUNT=0
    # also turns it off, without editing this file.
    "show_account": True,
    # System RAM in use out of the total. Linux and macOS.
    "show_memory": True,
    # The --agent name and the worktree, shown only when there is one.
    "show_agent": True,
    # Per-call token detail — off by default, one line has no room for it.
    "show_input_tokens": False,
    "show_cache_split": False,
    "show_output_tokens": False,
    # Session activity rather than usage — off by default.
    "show_duration": False,
    "show_lines_changed": False,
    # Colour thresholds, as percent used.
    "warn_at": 60.0,
    "crit_at": 85.0,
    "colour": True,
    # Nerd Font glyphs instead of text labels. Turn off in a terminal whose
    # font lacks them, or they draw as boxes. STATUSLINE_ICONS=0 also turns
    # them off, without editing this file.
    "icons": True,
    # Layout. The separator is drawn dim, so the values stand out.
    "separator": " • ",
    # When the terminal is too narrow, move fields onto a second line before
    # shedding anything. 1 keeps everything on one line, dropping detail and
    # then fields instead.
    "max_lines": 2,
    "fallback_width": 80,
    # A stuck git (huge repo, locked index) must not blank the line.
    "git_timeout": 0.5,
}

# Font Awesome codepoints: the most stable across Nerd Font versions.
ICONS = {
    "cwd": "\uf07c",  # nf-fa-folder_open
    "five_hour": "\uf017",  # nf-fa-clock_o
    "seven_day": "\uf073",  # nf-fa-calendar
    "context": "\uf1c0",  # nf-fa-database
    "cost": "\uf0d6",  # nf-fa-money
    "model": "\uf2db",  # nf-fa-microchip
    "git": "\ue0a0",  # nf-pl-branch
    "account": "\uf007",  # nf-fa-user
    "memory": "\uefc5",  # nf-fa-memory
    "agent": "\uf21b",  # nf-fa-user_secret
    "worktree": "\uf126",  # nf-fa-code_fork
    "fast": "\uf0e7",  # nf-fa-bolt
    "style": "\uf1fc",  # nf-fa-paint_brush
}

# What `icons: False` shows instead; a missing key means no label at all.
TEXT_LABELS = {
    "five_hour": "5h",
    "seven_day": "7d",
    # A bare name would read as a directory or branch.
    "agent": "agent",
    "worktree": "worktree",
    "fast": "fast",
    "style": "style",
}

GREEN, YELLOW, RED, BLUE, MAGENTA, CYAN, DIM, RESET = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[34m",
    "\033[35m",
    "\033[36m",
    "\033[2m",
    "\033[0m",
)

ANSI_RE = re.compile(r"\033\[[0-9;]*m")
# C0 and C1 control characters: a folder name carrying one could send the
# terminal an escape sequence.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def dig(obj, *path):
    """Walk nested dicts, returning None if any level is missing or not a dict."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def use_colour() -> bool:
    # https://no-color.org/ — any non-empty value disables colour.
    return CONFIG["colour"] and not os.environ.get("NO_COLOR")


def use_icons() -> bool:
    return CONFIG["icons"] and os.environ.get("STATUSLINE_ICONS") != "0"


def paint(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if use_colour() else text


def labelled(key: str, text: str) -> str:
    """Prefix `text` with the segment's icon, or its text label as fallback."""
    label = ICONS[key] if use_icons() else TEXT_LABELS.get(key, "")
    return f"{label} {text}" if label else text


def at_stage(stage: int, rich: str, sparse: str) -> list[str]:
    """Variants that keep `rich` until shrink level `stage`, then go `sparse`.

    fit() steps every segment down one variant per level, so padding the rich
    variant sets the order segments shrink in: stage 1 sheds first."""
    return [rich] * stage + [sparse]


def colour_for(pct: float) -> str:
    if pct >= CONFIG["crit_at"]:
        return RED
    if pct >= CONFIG["warn_at"]:
        return YELLOW
    return GREEN


def alert(pct: float) -> str:
    """' ⚠' past crit_at, so a critical value reads without colour too."""
    return paint(" ⚠", RED) if pct >= CONFIG["crit_at"] else ""


def fmt_tokens(n) -> str:
    """16700 -> '16.7k', 200000 -> '200k', 1000000 -> '1M'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        v = n / 1000
        return f"{v:.0f}k" if abs(v - round(v)) < 0.05 else f"{v:.1f}k"
    v = n / 1_000_000
    return f"{v:.0f}M" if abs(v - round(v)) < 0.005 else f"{v:.2f}M"


def fmt_pct(pct: float) -> str:
    """One decimal, but drop it when it adds nothing (23.0% -> 23%)."""
    return f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%"


def half_up(x: float) -> int:
    # round() goes to the even neighbour (476.5 -> 476); counts read better
    # rounding halves up.
    return int(x + 0.5)


def fmt_tokens_whole(n) -> str:
    """Whole numbers, for the context field: 15500 -> '16k', 476500 -> '477k',
    1250000 -> '1M'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n < 1000:
        return str(n)
    k = half_up(n / 1000)
    return f"{k}k" if k < 1000 else f"{half_up(n / 1_000_000)}M"


def fmt_reset(epoch) -> str | None:
    """Absolute local reset time. Same day -> '19:45', this week -> 'Thu 14:00',
    further out -> '12 Aug 14:00'."""
    if epoch is None:
        return None
    try:
        when = datetime.fromtimestamp(float(epoch))
    except (ValueError, OverflowError, OSError):
        return None
    now = datetime.now()
    delta_days = (when.date() - now.date()).days
    if delta_days == 0:
        return when.strftime("%H:%M")
    if 0 < delta_days <= 6:
        return when.strftime("%a %H:%M")
    return when.strftime("%-d %b %H:%M")


def fmt_duration(ms) -> str | None:
    if not ms:
        return None
    total = int(ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def printable(text: str) -> str:
    return CONTROL_RE.sub("", text)


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def fit(segments: list[tuple[int, list[str]]], width: int, max_lines: int = 1) -> str:
    """Lay segments out in at most `max_lines` lines of `width`, shrinking in
    two stages; the lines come back joined by newlines.

    Each segment carries one or more variants, richest first. First try every
    segment at its richest variant, then step all segments down a variant at a
    time. Only once everything is at its sparsest do we start dropping whole
    segments, highest priority number first. At each step the fields are
    packed in order onto as few lines as they need, so a second line is used
    before anything is shed. Priority 0 is never dropped, so a layout that
    still overflows is emitted as-is rather than mangled.
    """
    sep = paint(CONFIG["separator"], DIM)

    def pack(texts):
        """Fields in order, as many to a line as fit; a field is never split."""
        lines: list[list[str]] = [[]]
        for text in texts:
            if lines[-1] and visible_len(sep.join(lines[-1] + [text])) > width:
                lines.append([])
            lines[-1].append(text)
        return [sep.join(line) for line in lines]

    def attempt(segs, level):
        lines = pack([v[min(level, len(v) - 1)] for _, v in segs])
        fits = len(lines) <= max_lines and all(visible_len(line) <= width for line in lines)
        return lines, fits

    def overflowing(lines):
        # Nothing left to shed: keep the line count, let the last line run long.
        return "\n".join(lines[: max_lines - 1] + [sep.join(lines[max_lines - 1 :])])

    depth = max((len(v) for _, v in segments), default=1)
    for level in range(depth):
        lines, fits = attempt(segments, level)
        if fits:
            return "\n".join(lines)

    kept = list(segments)
    while kept:
        lines, fits = attempt(kept, depth - 1)
        if fits:
            return "\n".join(lines)
        droppable = [p for p, _ in kept if p > 0]
        if not droppable:
            return overflowing(lines)
        worst = max(droppable)
        # Drop one at a time, last occurrence first, for a stable shrink order.
        for i in range(len(kept) - 1, -1, -1):
            if kept[i][0] == worst:
                del kept[i]
                break
    return ""


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------


def session_dir(data: dict) -> str | None:
    path = dig(data, "workspace", "current_dir") or data.get("cwd")
    return path if isinstance(path, str) and path else None


def cwd_segment(data: dict) -> tuple[int, list[str]] | None:
    """Home as '~', deep paths trimmed to '~/…/leaf', the leaf alone when narrow."""
    path = session_dir(data)
    if path is None:
        return None
    path = printable(path)
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + "/"):
        anchor, rest = "~", path[len(home) :].strip("/")
    else:
        anchor, rest = "", path.strip("/")
    parts = rest.split("/") if rest else []
    if not parts:
        return (1, [labelled("cwd", anchor or "/")])
    full = f"{anchor}/{rest}"
    trimmed = full if len(parts) <= 2 else f"{anchor}/…/{parts[-1]}"
    return (1, at_stage(3, labelled("cwd", trimmed), labelled("cwd", parts[-1])))


def quota_segment(window: dict | None, key: str) -> tuple[int, list[str]] | None:
    """One rate-limit window. Returns None when the window is absent, so an
    unknown quota is omitted rather than rendered as 0%."""
    if not isinstance(window, dict):
        return None
    pct = window.get("used_percentage")
    if pct is None:
        return None
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return None

    compact = labelled(key, paint(fmt_pct(pct), colour_for(pct)) + alert(pct))
    reset = fmt_reset(window.get("resets_at"))
    # The percentage matters more than the reset time, so on a narrow terminal
    # we shed the reset rather than the whole window.
    variants = at_stage(1, f"{compact} [{reset}]", compact) if reset else [compact]
    return (0, variants)


def quota_segments(data: dict) -> list[tuple[int, list[str]]]:
    limits = data.get("rate_limits")
    if not isinstance(limits, dict):
        return []
    segs = []
    for key in ("five_hour", "seven_day"):
        seg = quota_segment(limits.get(key), key)
        if seg:
            segs.append(seg)
    return segs


def cost_segment(data: dict) -> tuple[int, list[str]] | None:
    """What an API-key session has cost so far. Claude Code prices every
    session at API rates, so the figure is a bill only without the
    subscription's rate_limits; $0, before the first response, says nothing."""
    if data.get("rate_limits") is not None:
        return None
    try:
        cost = float(dig(data, "cost", "total_cost_usd"))
    except (TypeError, ValueError):
        return None
    if cost <= 0:
        return None
    # In place of the quotas an API key lacks, so never dropped either.
    return (0, [labelled("cost", f"${cost:.2f}")])


def context_segments(data: dict) -> list[tuple[int, list[str]]]:
    ctx = data.get("context_window")
    if not isinstance(ctx, dict):
        return []

    segs: list[tuple[int, list[str]]] = []
    size = ctx.get("context_window_size")
    used = ctx.get("total_input_tokens")
    pct = ctx.get("used_percentage")
    usage = ctx.get("current_usage")
    usage = usage if isinstance(usage, dict) else {}

    # used_percentage can be null early in a session; derive it from the
    # input-only components so it matches Claude Code's own calculation.
    if pct is None and size:
        parts = [
            usage.get("input_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("cache_read_input_tokens"),
        ]
        if any(p is not None for p in parts):
            derived = sum(p or 0 for p in parts)
            pct = derived / float(size) * 100
            if used is None:
                used = derived

    try:
        pct = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct = None

    # Whole numbers here: the decimals took room without changing a decision.
    used_s, size_s = fmt_tokens_whole(used), fmt_tokens_whole(size)
    if used_s != "—" or size_s != "—":
        full = labelled("context", f"{used_s}/{size_s}")
        variants = [full]
        if pct is not None:
            shown = paint(f"{half_up(pct)}%", colour_for(pct))
            # On a narrow terminal keep the raw counts, shed the percentage,
            # but not the warning.
            variants = at_stage(2, f"{full} {shown}{alert(pct)}", full + alert(pct))
        segs.append((0, variants))

    if CONFIG["show_input_tokens"] and usage.get("input_tokens") is not None:
        short = f"in {fmt_tokens(usage['input_tokens'])}"
        variants = [short]
        if CONFIG["show_cache_split"]:
            w = usage.get("cache_creation_input_tokens")
            r = usage.get("cache_read_input_tokens")
            if w is not None or r is not None:
                cache = f" (cache w{fmt_tokens(w or 0)} r{fmt_tokens(r or 0)})"
                variants = [short + cache, short]
        segs.append((6, variants))

    if CONFIG["show_output_tokens"] and usage.get("output_tokens") is not None:
        segs.append((5, [f"out {fmt_tokens(usage['output_tokens'])}"]))

    if CONFIG["show_duration"]:
        dur = fmt_duration(dig(data, "cost", "total_duration_ms"))
        if dur:
            segs.append((7, [dur]))

    if CONFIG["show_lines_changed"]:
        added = dig(data, "cost", "total_lines_added")
        removed = dig(data, "cost", "total_lines_removed")
        if added or removed:
            segs.append((8, [f"+{added or 0}/-{removed or 0}"]))

    return segs


def model_segment(data: dict) -> tuple[int, list[str]] | None:
    name = dig(data, "model", "display_name") or dig(data, "model", "id")
    if not isinstance(name, str) or not name:
        return None
    short = labelled("model", name)
    rich = short
    # Absent before the first turn and on models without effort support.
    effort = dig(data, "effort", "level")
    if isinstance(effort, str) and effort:
        rich += f" ({effort})"
    # Fast mode spends the usage limits sooner. Sheds with the effort level.
    if data.get("fast_mode") is True:
        rich += " " + (ICONS["fast"] if use_icons() else TEXT_LABELS["fast"])
    return (2, at_stage(5, rich, short) if rich != short else [short])


def output_style_segment(data: dict) -> tuple[int, list[str]] | None:
    """The output style, hidden while it's the default: every reply reads
    differently under another one, and it's easy to forget it's on."""
    name = dig(data, "output_style", "name")
    if not isinstance(name, str) or not name or name == "default":
        return None
    # Drops early when narrow, right after the account.
    return (5, [labelled("style", printable(name))])


def git_status(path: str) -> str | None:
    """`git status` porcelain v2 output, or None outside a repo or on any failure."""
    try:
        out = subprocess.run(
            # A repo's own .git/config could name a command to run as its
            # fsmonitor; never run it.
            ["git", "-C", path, "-c", "core.fsmonitor=false", "status", "--porcelain=v2", "--branch"],
            capture_output=True,
            text=True,
            timeout=CONFIG["git_timeout"],
            # Read-only: don't take the index lock Claude's own git calls need.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def read_capped(path: Path, limit: int = 4096) -> str | None:
    """At most `limit` bytes of a regular file, or None. A repo that arrived
    as an archive controls its .git: a link there to /dev/zero, or a FIFO,
    must not hang the line or fill memory."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None
        with open(path, "rb") as f:
            return os.fsdecode(f.read(limit))
    except (OSError, ValueError):
        return None


def git_dirs(path: str) -> tuple[Path, Path, Path] | None:
    """(worktree root, its git dir, the repo's common git dir), found without
    running git. In a linked worktree or a submodule .git is a file naming the
    git dir; a worktree's git dir names the common one in `commondir`."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        dot = d / ".git"
        if dot.is_dir():
            return d, dot, dot
        if dot.is_file():
            text = read_capped(dot)
            if text is None or not text.startswith("gitdir:"):
                return None
            git_dir = (d / text[len("gitdir:") :].strip()).resolve()
            common_rel = read_capped(git_dir / "commondir")
            common = (git_dir / common_rel.strip()).resolve() if common_rel else git_dir
            return d, git_dir, common
    return None


def repo_name(path: str) -> str | None:
    """The repository's folder name; in a linked worktree, the main repo's,
    not the worktree's."""
    dirs = git_dirs(path)
    if dirs is None:
        return None
    root, git_dir, common = dirs
    if common == git_dir:
        return root.name
    # proj/.git -> proj; a bare repo's proj.git -> proj.
    name = common.parent.name if common.name == ".git" else common.name
    return name[: -len(".git")] if name.endswith(".git") else name


def git_operation(git_dir: Path) -> tuple[str, str | None] | None:
    """The operation in progress, named as Starship names it ('REBASE 1/3',
    'MERGE', ...), with the branch a rebase is rewriting when it says."""

    def read(name: str) -> str | None:
        text = read_capped(git_dir / name)
        return text.strip() or None if text else None

    for sub, step, total in (("rebase-merge", "msgnum", "end"), ("rebase-apply", "next", "last")):
        if (git_dir / sub).is_dir():
            kind = "AM" if (git_dir / sub / "applying").exists() else "REBASE"
            at, of = read(f"{sub}/{step}"), read(f"{sub}/{total}")
            branch = read(f"{sub}/head-name")
            if branch and branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/") :]
            else:
                branch = None
            return (f"{kind} {at}/{of}" if at and of else kind), branch
    for marker, label in (
        ("MERGE_HEAD", "MERGE"),
        ("CHERRY_PICK_HEAD", "CHERRY-PICK"),
        ("REVERT_HEAD", "REVERT"),
        ("BISECT_LOG", "BISECT"),
    ):
        if (git_dir / marker).exists():
            return label, None
    return None


def stash_count(common: Path) -> int:
    """Entries in the stash, one per line of its reflog: no git call, and no
    --show-stash, which a git older than 2.35 refuses. 1 MiB holds thousands
    of entries."""
    log = read_capped(common / "logs" / "refs" / "stash", 2**20)
    return log.count("\n") if log else 0


def git_segment(data: dict) -> tuple[int, list[str]] | None:
    """'repo:branch', '|REBASE 1/3' and the like mid-operation, then
    Starship's symbols: =conflicted !modified +staged ?untracked ✘deleted
    $stashed ⇡ahead ⇣behind, each omitted at zero."""
    path = session_dir(data)
    status = git_status(path) if path else None
    if status is None:
        return None

    head = oid = None
    ahead = behind = conflicted = modified = staged = untracked = deleted = 0
    for line in status.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.split()[2]
        elif line.startswith("# branch.head "):
            head = line.split()[2]
        elif line.startswith("# branch.ab "):
            a, b = line.split()[2:4]
            ahead, behind = int(a[1:]), int(b[1:])
        elif line.startswith("? "):
            untracked += 1
        elif line[:2] in ("1 ", "2 ", "u "):
            # XY: index (staged) status, then worktree status; '.' is unchanged.
            if line[0] == "u":
                conflicted += 1  # whatever each side did, it waits on you
                continue
            x, y = line[2], line[3]
            if "D" in (x, y):
                deleted += 1
            if x not in ".D":
                staged += 1
            if y in "MT":
                modified += 1

    dirs = git_dirs(path)
    operation = git_operation(dirs[1]) if dirs else None
    if head == "(detached)" and operation and operation[1]:
        head = operation[1]  # a rebase detaches HEAD; name the branch it rewrites
    elif head == "(detached)" and oid:
        head = f"@{oid[:7]}"
    if not head:
        return None
    if operation:
        # Kept when narrow, like the branch: it changes what any command does.
        head = f"{printable(head)}|{paint(operation[0], YELLOW)}"
    repo = repo_name(path)
    base = labelled("git", f"{printable(repo)}:{head}" if repo else head)
    # Staged green, unstaged yellow and untracked blue, as `git status` and
    # Powerlevel10k colour them; arrows apart so push and pull read distinctly.
    counts = (
        ("=", conflicted, RED),
        ("!", modified, YELLOW),
        ("+", staged, GREEN),
        ("?", untracked, BLUE),
        ("✘", deleted, RED),
        ("$", stash_count(dirs[2]) if dirs else 0, DIM),
        ("⇡", ahead, CYAN),
        ("⇣", behind, MAGENTA),
    )
    symbols = " ".join(paint(f"{sym}{n}", code) for sym, n, code in counts if n)
    return (3, at_stage(4, f"{base} {symbols}", base) if symbols else [base])


def agent_segment(data: dict) -> tuple[int, list[str]] | None:
    """The --agent name and the worktree the session runs in: Claude's own
    worktree, else any linked git worktree. None for a plain session."""
    parts = []
    agent = dig(data, "agent", "name")
    if isinstance(agent, str) and agent:
        parts.append(labelled("agent", printable(agent)))
    tree = dig(data, "worktree", "name") or dig(data, "workspace", "git_worktree")
    if isinstance(tree, str) and tree:
        parts.append(labelled("worktree", printable(tree)))
    return (4, [" ".join(parts)]) if parts else None


def account_email() -> str | None:
    """The logged-in account's email, or None (API key, logged out, no file).

    Claude Code keeps it in .claude.json: inside CLAUDE_CONFIG_DIR when that
    is set (one dir per account), else in the home directory. Only this one
    field is read; the login token lives in another file, never opened here."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    path = Path(config_dir) / ".claude.json" if config_dir else Path.home() / ".claude.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    email = dig(data, "oauthAccount", "emailAddress")
    return email if isinstance(email, str) and email else None


def account_segment() -> tuple[int, list[str]] | None:
    email = account_email()
    # Highest priority number: the first whole field to drop when narrow.
    return (9, [labelled("account", email)]) if email else None


def fmt_size(n: int) -> str:
    """Binary units, as free -h and system monitors count them:
    8 GiB -> '8GB', 7.6 GiB -> '7.6GB', 512 MiB -> '512MB'."""
    gib = n / 2**30
    if gib < 1:
        return f"{n / 2**20:.0f}MB"
    return f"{gib:.0f}GB" if abs(gib - round(gib)) < 0.05 else f"{gib:.1f}GB"


def parse_meminfo(text: str) -> tuple[int, int] | None:
    """(used, total) bytes. Used is total minus available, so the page cache
    the kernel hands back on demand does not count as used."""
    fields = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if rest.split():
            fields[key] = int(rest.split()[0]) * 1024
    total, available = fields.get("MemTotal"), fields.get("MemAvailable")
    if not total or available is None:
        return None
    return total - available, total


def parse_vm_stat(text: str, total: int) -> tuple[int, int] | None:
    """(used, total) bytes, as Activity Monitor's "Memory Used" counts it:
    app memory (anonymous minus purgeable), wired and compressed."""
    size = re.search(r"page size of (\d+) bytes", text)
    pages = {k.strip(): int(v) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", text, re.M)}
    keys = ("Anonymous pages", "Pages purgeable", "Pages wired down", "Pages occupied by compressor")
    if not size or not total or any(k not in pages for k in keys):
        return None
    used_pages = pages[keys[0]] - pages[keys[1]] + pages[keys[2]] + pages[keys[3]]
    return used_pages * int(size.group(1)), total


def memory_reading() -> tuple[int, int] | None:
    """System memory (used, total) in bytes; None off Linux and macOS."""
    try:
        if sys.platform.startswith("linux"):
            return parse_meminfo(Path("/proc/meminfo").read_text())
        if sys.platform == "darwin":
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=CONFIG["git_timeout"])
            return parse_vm_stat(out.stdout, total) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def memory_segment() -> tuple[int, list[str]] | None:
    reading = memory_reading()
    if reading is None:
        return None
    used, total = reading
    # Coloured by the share in use, like the usage limits.
    pct = used / total * 100
    shown = paint(fmt_size(used), colour_for(pct))
    return (4, [labelled("memory", f"{shown}/{fmt_size(total)}{alert(pct)}")])


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def terminal_width() -> int:
    # tput and shutil.get_terminal_size can't see the real terminal here —
    # Claude Code captures our stdout. It sets COLUMNS for us instead.
    try:
        return max(20, int(os.environ.get("COLUMNS", "")))
    except ValueError:
        return CONFIG["fallback_width"]


def main() -> None:
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        data = {}

    # Priority decides what drops when even the sparsest variants overflow:
    # highest number first, so account, output style, agent, memory, git,
    # model and cwd;
    # quota, cost and context (priority 0) never drop.
    segments: list[tuple[int, list[str]]] = []
    if CONFIG["show_cwd"]:
        segments += filter(None, [cwd_segment(data)])
    if CONFIG["show_cost"]:
        segments += filter(None, [cost_segment(data)])
    if CONFIG["show_quota"]:
        segments += quota_segments(data)
    if CONFIG["show_context"]:
        segments += context_segments(data)
    if CONFIG["show_model"]:
        segments += filter(None, [model_segment(data)])
    if CONFIG["show_output_style"]:
        segments += filter(None, [output_style_segment(data)])
    if CONFIG["show_memory"]:
        segments += filter(None, [memory_segment()])
    if CONFIG["show_git"]:
        segments += filter(None, [git_segment(data)])
    if CONFIG["show_agent"]:
        segments += filter(None, [agent_segment(data)])
    if CONFIG["show_account"] and os.environ.get("STATUSLINE_ACCOUNT") != "0":
        segments += filter(None, [account_segment()])

    if not segments:
        return  # nothing known yet — print nothing rather than an empty shell
    lines = fit(segments, terminal_width(), max(1, CONFIG["max_lines"]))
    if lines:
        print(lines)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A traceback would leave the statusline blank, so degrade to a marker.
        print(paint("usage unavailable", DIM))
