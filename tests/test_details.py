"""The optional details after the context: the last call's input tokens (and
their cache split) and output tokens, the session's duration and the lines
it changed. All off by default."""

from __future__ import annotations

import unittest
from unittest import mock

import statusline
from tests.payloads import base
from tests.support import HOME, NOW, changed, environment, porcelain, run_main, untracked

ALL = {
    "show_input_tokens": True,
    "show_cache_split": True,
    "show_output_tokens": True,
    "show_duration": True,
    "show_lines_changed": True,
}
BEFORE = "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k 8%"
AFTER = "Opus 5.5 (high)"
GIT = porcelain(changed(".M"), untracked(), ab="+2 -0")
ACCOUNT = "me@example.com"
MEMORY = (int(7.6 * 2**30), int(14.8 * 2**30))


def payload(usage=(), cost=()) -> dict:
    """The full payload, with these current_usage and cost fields changed."""
    data = base(NOW.timestamp(), cwd=f"{HOME}/projects/work/demo")
    # No reset times: shorter lines, and none that hang on the time zone.
    for window in data["rate_limits"].values():
        del window["resets_at"]
    data["context_window"]["current_usage"].update(usage)
    data["cost"].update(cost)
    return data


def line(data=None, columns=300, **settings) -> str:
    with environment(), mock.patch.dict(statusline.CONFIG, settings):
        return run_main(data or payload(), columns)


class DetailFieldsTest(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(line(), f"{BEFORE} • {AFTER}")

    def test_each_alone_follows_the_context(self):
        cases = {
            "show_input_tokens": "in 8.5k",
            "show_output_tokens": "out 1.2k",
            "show_duration": "2m15s",
            "show_lines_changed": "+156/-23",
        }
        for key, text in cases.items():
            with self.subTest(key):
                self.assertEqual(line(**{key: True}), f"{BEFORE} • {text} • {AFTER}")

    def test_all_together_in_order(self):
        details = "in 8.5k (cache w5k r2k) • out 1.2k • 2m15s • +156/-23"
        self.assertEqual(line(**ALL), f"{BEFORE} • {details} • {AFTER}")

    def test_the_cache_split_needs_the_input_tokens(self):
        self.assertEqual(line(show_cache_split=True), f"{BEFORE} • {AFTER}")

    def test_a_missing_cache_side_counts_as_zero(self):
        cases = {
            "cache_creation_input_tokens": "in 8.5k (cache w0 r2k)",
            "cache_read_input_tokens": "in 8.5k (cache w5k r0)",
        }
        for key, text in cases.items():
            with self.subTest(key):
                data = payload(usage={key: None})
                self.assertIn(f" • {text} • ", line(data, show_input_tokens=True, show_cache_split=True))

    def test_no_cache_figures_shows_the_input_alone(self):
        data = payload(usage={"cache_creation_input_tokens": None, "cache_read_input_tokens": None})
        self.assertEqual(line(data, show_input_tokens=True, show_cache_split=True), f"{BEFORE} • in 8.5k • {AFTER}")

    def test_each_is_hidden_when_its_value_is_missing(self):
        no_usage, no_cost = payload(), payload()
        no_usage["context_window"]["current_usage"] = None
        del no_cost["cost"]
        cases = {
            "input tokens": (payload(usage={"input_tokens": None}), ["show_input_tokens", "show_cache_split"]),
            "output tokens": (payload(usage={"output_tokens": None}), ["show_output_tokens"]),
            "no usage": (no_usage, ["show_input_tokens", "show_cache_split", "show_output_tokens"]),
            "duration": (payload(cost={"total_duration_ms": None}), ["show_duration"]),
            "zero duration": (payload(cost={"total_duration_ms": 0}), ["show_duration"]),
            "no cost": (no_cost, ["show_duration", "show_lines_changed"]),
        }
        for name, (data, keys) in cases.items():
            with self.subTest(name):
                self.assertEqual(line(data, **dict.fromkeys(keys, True)), f"{BEFORE} • {AFTER}")

    def test_lines_changed(self):
        cases = [
            (156, None, "+156/-0"),
            (156, 0, "+156/-0"),
            (None, 23, "+0/-23"),
            (0, 23, "+0/-23"),
            (None, None, None),
            (0, 0, None),
        ]
        for added, removed, text in cases:
            with self.subTest(added=added, removed=removed):
                data = payload(cost={"total_lines_added": added, "total_lines_removed": removed})
                shown = f" • {text}" if text else ""
                self.assertEqual(line(data, show_lines_changed=True), f"{BEFORE}{shown} • {AFTER}")


class DetailShrinkTest(unittest.TestCase):
    """Narrowing the terminal sheds the cache split first, then the usual
    detail; then whole fields go, highest priority number first: account 9,
    lines 8, duration 7, input 6, output 5, then memory 4 and on."""

    EXPECTED = [
        "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k 8% • in 8.5k (cache w5k r2k) • out 1.2k • 2m15s • "
        "+156/-23 • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2 • me@example.com",
        # 1. the cache split
        "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k 8% • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2 • me@example.com",
        # 2. context's percentage, 3. cwd, 4. git symbols, 5. effort
        "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2 • me@example.com",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2 • me@example.com",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 (high) • 7.6GB/14.8GB • repo:main • me@example.com",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 • 7.6GB/14.8GB • repo:main • me@example.com",
        # then whole fields: account, lines, duration, input, output, memory, git, model, cwd
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • +156/-23 • "
        "Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • 2m15s • Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • in 8.5k • out 1.2k • Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • out 1.2k • Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k",
        "5h 23.5% • 7d 41.2% • 16k/200k",
    ]

    def shrink(self, **settings) -> list[str]:
        """Each distinct line from wide to narrow."""
        seen: list[str] = []
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY), mock.patch.dict(statusline.CONFIG, settings):
            for width in range(300, 19, -1):
                line = run_main(payload(), columns=width)
                if not seen or line != seen[-1]:
                    seen.append(line)
        return seen

    def test_shrink_sequence(self):
        self.assertEqual(self.shrink(**ALL), self.EXPECTED)

    def test_the_account_drops_first_wherever_it_sits(self):
        # Among equals the later field drops first, so this would catch a
        # detail whose priority had crept up to the account's.
        seen = self.shrink(**ALL, order=["account"])
        no_account = next(line for line in seen if ACCOUNT not in line)
        self.assertIn("+156/-23", no_account)


if __name__ == "__main__":
    unittest.main()
