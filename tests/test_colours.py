"""The usage colours: green below warn_at, yellow from it, red from crit_at,
on the quotas, the context and memory alike."""

from __future__ import annotations

import unittest
from unittest import mock

import statusline
from statusline import GREEN, RED, RESET, YELLOW
from tests.payloads import base
from tests.support import HOME, NOW, environment, run_main

GIB = 2**30
CUSTOM = {"warn_at": 25, "crit_at": 50}


def line(five_hour=23.5, context=8, memory=(4 * GIB, 16 * GIB), **settings) -> str:
    """The line, in colour, with these figures."""
    data = base(NOW.timestamp(), cwd=f"{HOME}/demo")
    data["rate_limits"]["five_hour"]["used_percentage"] = five_hour
    data["context_window"]["used_percentage"] = context
    with environment(colour=True, memory=memory), mock.patch.dict(statusline.CONFIG, settings):
        return run_main(data)


class UsageColourTest(unittest.TestCase):
    """Each boundary from just below it and exactly on it, with the default
    thresholds and with the user's own."""

    def test_quota(self):
        cases = [
            ({}, 59.9, "59.9%", GREEN),
            ({}, 60, "60%", YELLOW),
            ({}, 84.9, "84.9%", YELLOW),
            ({}, 85, "85%", RED),
            (CUSTOM, 24.9, "24.9%", GREEN),
            (CUSTOM, 25, "25%", YELLOW),
            (CUSTOM, 49.9, "49.9%", YELLOW),
            (CUSTOM, 50, "50%", RED),
        ]
        for settings, pct, text, colour in cases:
            with self.subTest(pct, **settings):
                self.assertIn(f"5h {colour}{text}{RESET}", line(five_hour=pct, **settings))

    def test_context(self):
        cases = [
            ({}, 59, GREEN),
            ({}, 60, YELLOW),
            ({}, 84, YELLOW),
            ({}, 85, RED),
            (CUSTOM, 24, GREEN),
            (CUSTOM, 25, YELLOW),
            (CUSTOM, 49, YELLOW),
            (CUSTOM, 50, RED),
        ]
        for settings, pct, colour in cases:
            with self.subTest(pct, **settings):
                self.assertIn(f"16k/200k {colour}{pct}%{RESET}", line(context=pct, **settings))

    def test_memory(self):
        # Out of 20GB, whole GBs make exact percentages: 12GB is 60%, 17GB 85%.
        cases = [
            ({}, 11.9, "11.9GB", GREEN),
            ({}, 12, "12GB", YELLOW),
            ({}, 16.9, "16.9GB", YELLOW),
            ({}, 17, "17GB", RED),
            (CUSTOM, 4.9, "4.9GB", GREEN),
            (CUSTOM, 5, "5GB", YELLOW),
            (CUSTOM, 9.9, "9.9GB", YELLOW),
            (CUSTOM, 10, "10GB", RED),
        ]
        for settings, used, text, colour in cases:
            with self.subTest(used, **settings):
                memory = (int(used * GIB), 20 * GIB)
                self.assertIn(f"{colour}{text}{RESET}/20GB", line(memory=memory, **settings))


if __name__ == "__main__":
    unittest.main()
