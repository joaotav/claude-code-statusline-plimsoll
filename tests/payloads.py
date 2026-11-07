"""Statusline stdin payloads: the full one and each degradation path.

Shared by the tests and by scripts/make-fixtures.py. Reset times are relative
to `now` (epoch seconds), so the same-day / this-week / further-out
formatting branches stay exercised whenever they are built.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOUR = 3600
DAY = 24 * HOUR


def base(now: float, cwd: str = str(ROOT)) -> dict:
    return {
        "cwd": cwd,
        "session_id": "fixture-session-0001",
        "transcript_path": "/tmp/transcript.jsonl",
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "workspace": {
            "current_dir": cwd,
            "project_dir": cwd,
            "added_dirs": [],
        },
        "version": "2.1.220",
        "output_style": {"name": "default"},
        "cost": {
            "total_cost_usd": 0.01234,
            "total_duration_ms": 135000,
            "total_api_duration_ms": 2300,
            "total_lines_added": 156,
            "total_lines_removed": 23,
        },
        "context_window": {
            "total_input_tokens": 15500,
            "total_output_tokens": 1200,
            "context_window_size": 200000,
            "used_percentage": 8,
            "remaining_percentage": 92,
            "current_usage": {
                "input_tokens": 8500,
                "output_tokens": 1200,
                "cache_creation_input_tokens": 5000,
                "cache_read_input_tokens": 2000,
            },
        },
        "exceeds_200k_tokens": False,
        "rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": int(now + 2 * HOUR)},
            "seven_day": {"used_percentage": 41.2, "resets_at": int(now + 4 * DAY)},
        },
    }


def all_payloads(now: float, cwd: str = str(ROOT)) -> dict[str, dict]:
    p: dict[str, dict] = {}

    # Everything present — the happy path.
    p["full"] = base(now, cwd)

    # Pro/Max quota not yet known: before the first API response, or API-key auth.
    f = base(now, cwd)
    del f["rate_limits"]
    p["no-rate-limits"] = f

    # Windows can be absent independently.
    f = base(now, cwd)
    del f["rate_limits"]["seven_day"]
    p["one-window"] = f

    # Immediately after /compact, or before the first API call.
    f = base(now, cwd)
    f["context_window"]["current_usage"] = None
    f["context_window"]["used_percentage"] = None
    f["context_window"]["remaining_percentage"] = None
    f["context_window"]["total_input_tokens"] = 0
    f["context_window"]["total_output_tokens"] = 0
    p["null-usage"] = f

    # used_percentage null but current_usage present — exercises the derived path.
    f = base(now, cwd)
    f["context_window"]["used_percentage"] = None
    p["derived-pct"] = f

    # Brand new session: no quota yet, no context yet, no effort until the first
    # turn. Only cwd, model and git remain.
    f = base(now, cwd)
    del f["rate_limits"]
    del f["context_window"]
    del f["cost"]
    del f["effort"]
    p["empty"] = f

    # Model without effort support: the model shows alone.
    f = base(now, cwd)
    del f["effort"]
    p["no-effort"] = f

    # High usage: red thresholds and the >200k marker.
    f = base(now, cwd)
    f["rate_limits"]["five_hour"]["used_percentage"] = 94.0
    f["rate_limits"]["seven_day"]["used_percentage"] = 71.8
    f["context_window"]["total_input_tokens"] = 210000
    f["context_window"]["used_percentage"] = 96
    f["context_window"]["current_usage"] = {
        "input_tokens": 120000,
        "output_tokens": 8400,
        "cache_creation_input_tokens": 60000,
        "cache_read_input_tokens": 30000,
    }
    f["exceeds_200k_tokens"] = True
    p["maxed"] = f

    # Run with --agent inside a Claude worktree.
    f = base(now, cwd)
    f["agent"] = {"name": "security-reviewer"}
    f["worktree"] = {
        "name": "my-feature",
        "path": f"{cwd}/.claude/worktrees/my-feature",
        "branch": "worktree-my-feature",
        "original_cwd": cwd,
        "original_branch": "main",
    }
    p["agent-worktree"] = f

    # Reset further than a week out — exercises the date-prefixed branch.
    f = base(now, cwd)
    f["rate_limits"]["seven_day"]["resets_at"] = int(now + 10 * DAY)
    p["far-reset"] = f

    # cwd shapes: home itself, a deep path outside home, the root.
    for name, path in (
        ("cwd-home", str(Path.home())),
        ("cwd-deep", "/usr/share/doc/python3"),
        ("cwd-root", "/"),
    ):
        f = base(now, cwd)
        f["cwd"] = f["workspace"]["current_dir"] = path
        p[name] = f

    # Malformed input: wrong types where numbers are expected.
    p["garbage"] = {
        "rate_limits": {"five_hour": "not-a-dict", "seven_day": {"used_percentage": "abc"}},
        "context_window": {"context_window_size": "big", "current_usage": []},
        "cost": {"total_cost_usd": "free"},
    }

    return p
