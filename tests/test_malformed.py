"""Malformed payloads. A field of the wrong type, or a number no float holds,
hides that field or just the part it feeds; it never raises, which would
blank the whole line, and inf or nan is never printed."""

from __future__ import annotations

import itertools
import os
import re
import unittest
from unittest import mock

import statusline
from tests.payloads import base
from tests.support import HOME, NOW, environment, porcelain, run_main

DETAILS = {
    "show_input_tokens": True,
    "show_cache_split": True,
    "show_output_tokens": True,
    "show_duration": True,
    "show_lines_changed": True,
}
GIT = porcelain()
ACCOUNT = "me@example.com"
MEMORY = (2**30, 2**32)

# Wrong types and awkward numbers. JSON brings inf and nan too: 1e400 parses
# as inf, and Python's parser takes NaN and Infinity. An int of hundreds of
# digits parses whole, too big for a float.
JUNK = [
    None, 0, -1, 1.5, True, False, "x", "", [], {}, [1], {"a": 1},
    float("inf"), float("-inf"), float("nan"), 10**400, -(10**400), 2**63,
    "9" * 400, "1e400", "nan", "12.5",
]
# One of each kind that some field used to raise on, for the slower run
# through main().
KINDS = [None, "x", "12.5", [1], {}, float("inf"), float("nan"), 10**400, "9" * 400]
NON_FINITE = re.compile(r"\b(inf|nan)\b")


def everything() -> dict:
    """A payload with every field set, a cold cache among them."""
    data = base(NOW.timestamp(), cwd=f"{HOME}/demo")
    data.update(agent={"name": "reviewer"}, worktree={"name": "my-feature"}, fast_mode=True)
    data["output_style"]["name"] = "Explanatory"
    data["workspace"]["git_worktree"] = "hotfix"
    data["prompt_cache"].update(warm=False, recache_tokens_if_cold=152000)
    return data


def early_api_session() -> dict:
    """No quotas, so the cost shows, and no percentage yet, so it's derived."""
    data = everything()
    del data["rate_limits"]
    data["context_window"]["used_percentage"] = None
    return data


def paths(obj: dict, prefix: tuple = ()):
    """Every key path in `obj`, to leaves and to whole sub-objects."""
    for key, value in obj.items():
        yield prefix + (key,)
        if isinstance(value, dict):
            yield from paths(value, prefix + (key,))


def junked(data: dict, path: tuple, value) -> dict:
    """`data` with `value` at `path`, copying only the objects on the way."""
    data = target = dict(data)
    for key in path[:-1]:
        target[key] = dict(target[key])
        target = target[key]
    target[path[-1]] = value
    return data


# Text in the full line, with the payload fields it comes from. Junk anywhere
# else must leave it showing.
SHOWN = {
    # A current_dir of the wrong type hides the directory rather than falling
    # back to cwd, and git with it; display_name does the same to the model.
    "~/demo": ["cwd", "workspace.current_dir"],
    "5h 23.5%": ["rate_limits.five_hour.used_percentage"],
    "7d 41.2%": ["rate_limits.seven_day.used_percentage"],
    "16k/200k": ["context_window.total_input_tokens", "context_window.context_window_size"],
    "in 8.5k": ["context_window.current_usage.input_tokens"],
    "(cache w5k r2k)": [
        "context_window.current_usage.input_tokens",
        "context_window.current_usage.cache_creation_input_tokens",
        "context_window.current_usage.cache_read_input_tokens",
    ],
    "out 1.2k": ["context_window.current_usage.output_tokens"],
    # The context field draws these too, so they go with it.
    "2m15s": ["cost.total_duration_ms", "context_window"],
    "+156/-23": ["cost.total_lines_added", "cost.total_lines_removed", "context_window"],
    "Cold (152k)": ["prompt_cache.warm", "prompt_cache.recache_tokens_if_cold"],
    "Opus 5.5": ["model.display_name"],
    "(high)": ["effort.level", "model.display_name"],
    "style Explanatory": ["output_style.name"],
    "repo:main": ["cwd", "workspace.current_dir"],
    "agent reviewer": ["agent.name"],
    "worktree my-feature": ["worktree.name"],
    "me@example.com": [],
    "1GB/4GB": [],
}


def related(path: str, source: str) -> bool:
    """Whether junk at `path` replaces `source` or something holding it."""
    return path == source or source.startswith(path + ".") or path.startswith(source + ".")


def short(value) -> str:
    return repr(value)[:20]


class FuzzTest(unittest.TestCase):
    def test_no_field_raises_or_prints_inf_or_nan(self):
        bases = {"subscription": everything(), "early API session": early_api_session()}
        for (name, data), settings, git in itertools.product(bases.items(), ({}, DETAILS), (GIT, None)):
            with environment(git=git, account=ACCOUNT, memory=MEMORY), mock.patch.dict(statusline.CONFIG, settings):
                for path in paths(data):
                    for value in JUNK:
                        where = {"path": ".".join(path), "value": short(value), "details": bool(settings)}
                        with self.subTest(name, git=bool(git), **where):
                            # Wide, so no field is dropped before it is drawn.
                            line = statusline.render(junked(data, path, value), 5000)
                            # A string is shown as given where text is expected.
                            if not isinstance(value, str):
                                self.assertNotRegex(line, NON_FINITE)

    def test_the_rest_of_the_line_still_shows(self):
        data = everything()
        with (
            # Empty before environment() fills it: run_main copies it on every call.
            mock.patch.dict(os.environ, clear=True),
            environment(git=GIT, account=ACCOUNT, memory=MEMORY),
            mock.patch.dict(statusline.CONFIG, DETAILS),
        ):
            line = run_main(data)
            for text in SHOWN:
                self.assertIn(text, line)
            for path in map(".".join, paths(data)):
                for value in KINDS:
                    with self.subTest(path=path, value=short(value)):
                        line = run_main(junked(data, tuple(path.split(".")), value), columns=5000)
                        for text, sources in SHOWN.items():
                            if not any(related(path, source) for source in sources):
                                self.assertIn(text, line)


class RepairedFieldTest(unittest.TestCase):
    """What each field that used to raise shows instead."""

    def setUp(self):
        self.enterContext(environment())

    def test_a_junk_reset_time_keeps_the_percentage(self):
        for value in ([1], {"a": 1}, [], {}):
            with self.subTest(value):
                seg = statusline.quota_segment({"used_percentage": 23.5, "resets_at": value}, "five_hour")
                self.assertEqual(seg, (0, ["5h 23.5%"]))

    def test_an_unusable_quota_percentage_hides_its_window(self):
        for value in (float("inf"), float("-inf"), float("nan"), 10**400, "1e400", "nan"):
            with self.subTest(short(value)):
                self.assertIsNone(statusline.quota_segment({"used_percentage": value}, "five_hour"))

    def test_an_unusable_count_is_a_dash(self):
        for value in (float("inf"), float("-inf"), float("nan"), 10**400, "9" * 400):
            with self.subTest(short(value)):
                self.assertEqual(statusline.fmt_tokens(value), "—")
                self.assertEqual(statusline.fmt_tokens_whole(value), "—")
                ctx = {"context_window_size": 200000, "total_input_tokens": value, "used_percentage": 8}
                self.assertEqual(statusline.context_segments({"context_window": ctx})[0][1][0], "—/200k 8%")

    def test_an_unusable_window_size_is_a_dash(self):
        ctx = {"context_window_size": float("inf"), "total_input_tokens": 15500, "used_percentage": 8}
        self.assertEqual(statusline.context_segments({"context_window": ctx})[0][1][0], "16k/— 8%")

    def test_an_unusable_context_percentage_is_left_out(self):
        for value in (float("inf"), float("nan"), 10**400, "1e400"):
            with self.subTest(short(value)):
                ctx = {"context_window_size": 200000, "total_input_tokens": 15500, "used_percentage": value}
                self.assertEqual(statusline.context_segments({"context_window": ctx})[0][1], ["16k/200k"])

    def test_nothing_is_derived_from_unusable_parts(self):
        usage = {"input_tokens": 8500, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 2000}
        cases = [
            ({"context_window_size": 200000, "current_usage": dict(usage, input_tokens="x")}, ["—/200k"]),
            # The parts still make a count, without a size to take a share of.
            ({"context_window_size": "big", "current_usage": usage}, ["16k/—"]),
            ({"context_window_size": "0", "current_usage": usage}, ["16k/0"]),
        ]
        for ctx, expected in cases:
            with self.subTest(ctx["context_window_size"]):
                variants = statusline.context_segments({"context_window": dict(ctx, used_percentage=None)})[0][1]
                self.assertEqual(variants, expected)

    def test_an_unusable_duration_is_hidden(self):
        for value in ("x", "12.5", [1], {"a": 1}, float("inf"), float("nan")):
            with self.subTest(short(value)):
                self.assertIsNone(statusline.fmt_duration(value))

    def test_inf_or_nan_lines_changed_are_hidden(self):
        for value in (float("inf"), float("nan")):
            with self.subTest(short(value)), mock.patch.dict(statusline.CONFIG, {"show_lines_changed": True}):
                data = {"context_window": {}, "cost": {"total_lines_added": value, "total_lines_removed": 23}}
                self.assertEqual(statusline.context_segments(data), [])

    def test_an_unusable_cost_is_hidden(self):
        for value in (float("inf"), float("nan"), 10**400):
            with self.subTest(short(value)):
                self.assertIsNone(statusline.cost_segment({"cost": {"total_cost_usd": value}}))

    def test_an_unusable_cold_cache_size_is_hidden(self):
        for value in (float("inf"), float("nan")):
            with self.subTest(short(value)):
                data = {"prompt_cache": {"warm": False, "recache_tokens_if_cold": value}}
                self.assertIsNone(statusline.cache_segment(data))


if __name__ == "__main__":
    unittest.main()
