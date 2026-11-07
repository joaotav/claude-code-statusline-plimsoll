"""Value formatting: token counts, percentages, reset times and the cwd."""

from __future__ import annotations

import unittest

import statusline
from tests.support import HOME, environment, epoch


class FmtTokensTest(unittest.TestCase):
    def test_scales(self):
        cases = {
            999: "999",
            1000: "1k",
            16700: "16.7k",
            200000: "200k",
            476500: "476.5k",
            1_000_000: "1M",
            1_250_000: "1.25M",
        }
        for n, expected in cases.items():
            with self.subTest(n=n):
                self.assertEqual(statusline.fmt_tokens(n), expected)

    def test_non_numeric_is_a_dash(self):
        for value in (None, "big", []):
            with self.subTest(value=value):
                self.assertEqual(statusline.fmt_tokens(value), "—")


class FmtTokensWholeTest(unittest.TestCase):
    """The context field's counts: whole numbers, halves rounded up."""

    def test_scales(self):
        cases = {
            999: "999",
            15500: "16k",
            476500: "477k",
            200000: "200k",
            999_499: "999k",
            999_500: "1M",  # rounds to 1000k, so it moves up a unit
            1_250_000: "1M",
            1_500_000: "2M",
        }
        for n, expected in cases.items():
            with self.subTest(n=n):
                self.assertEqual(statusline.fmt_tokens_whole(n), expected)

    def test_non_numeric_is_a_dash(self):
        self.assertEqual(statusline.fmt_tokens_whole("big"), "—")


class ContextFieldTest(unittest.TestCase):
    def test_percentage_is_whole(self):
        data = {"context_window": {"context_window_size": 200000, "total_input_tokens": 15500, "used_percentage": 7.8}}
        with environment():
            variants = statusline.context_segments(data)[0][1]
        self.assertEqual(variants[0], "16k/200k 8%")
        self.assertEqual(variants[-1], "16k/200k")

    def test_critical_keeps_its_warning_when_narrow(self):
        data = {"context_window": {"context_window_size": 200000, "total_input_tokens": 190000, "used_percentage": 95}}
        with environment():
            variants = statusline.context_segments(data)[0][1]
        self.assertEqual(variants[0], "190k/200k 95% ⚠")
        self.assertEqual(variants[-1], "190k/200k ⚠")


class AlertTest(unittest.TestCase):
    def test_marks_only_from_crit_at(self):
        with environment():
            self.assertEqual(statusline.alert(84.9), "")
            self.assertEqual(statusline.alert(85), " ⚠")

    def test_quota_past_crit_at_is_marked(self):
        with environment():
            calm = statusline.quota_segment({"used_percentage": 60}, "five_hour")[1]
            critical = statusline.quota_segment({"used_percentage": 94}, "five_hour")[1]
        self.assertEqual(calm, ["5h 60%"])
        self.assertEqual(critical, ["5h 94% ⚠"])


class FmtPctTest(unittest.TestCase):
    def test_drops_a_decimal_that_adds_nothing(self):
        self.assertEqual(statusline.fmt_pct(23.0), "23%")
        self.assertEqual(statusline.fmt_pct(23.5), "23.5%")


class FmtResetTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(environment())

    def test_same_day_is_time_only(self):
        self.assertEqual(statusline.fmt_reset(epoch(hours=2)), "14:00")

    def test_this_week_is_weekday_and_time(self):
        self.assertEqual(statusline.fmt_reset(epoch(days=2)), "Fri 12:00")

    def test_further_out_is_date_and_time(self):
        self.assertEqual(statusline.fmt_reset(epoch(days=10)), "7 Nov 12:00")

    def test_unknown_or_invalid_is_none(self):
        for value in (None, "abc", float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(statusline.fmt_reset(value))


class CwdSegmentTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(environment())

    def variants(self, path):
        seg = statusline.cwd_segment({"cwd": path})
        return seg[1] if seg else None

    def test_home_is_tilde(self):
        self.assertEqual(self.variants(HOME), ["~"])

    def test_root_is_slash(self):
        self.assertEqual(self.variants("/"), ["/"])

    def test_shallow_path_is_shown_whole(self):
        self.assertEqual(self.variants(f"{HOME}/a/b")[0], "~/a/b")

    def test_deep_path_is_trimmed_then_shrinks_to_its_leaf(self):
        v = self.variants(f"{HOME}/a/b/c")
        self.assertEqual(v[0], "~/…/c")
        self.assertEqual(v[-1], "c")

    def test_deep_path_outside_home(self):
        self.assertEqual(self.variants("/usr/share/doc")[0], "/…/doc")

    def test_sibling_of_home_is_not_abbreviated(self):
        # /home/tester2 shares a prefix with HOME but is not under it.
        self.assertFalse(self.variants(f"{HOME}2/x")[0].startswith("~"))

    def test_workspace_dir_wins_over_cwd(self):
        data = {"cwd": "/elsewhere", "workspace": {"current_dir": HOME}}
        self.assertEqual(statusline.cwd_segment(data)[1], ["~"])

    def test_missing_cwd_is_no_segment(self):
        self.assertIsNone(statusline.cwd_segment({}))

    def test_control_characters_are_not_printed(self):
        # A folder name could carry a terminal escape (here, set the title).
        self.assertEqual(self.variants(f"{HOME}/a\033]0;x\007b\x9b")[0], "~/a]0;xb")


if __name__ == "__main__":
    unittest.main()
