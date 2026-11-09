"""The whole line: field order, the narrow-terminal shrink sequence, labels
and colour switches."""

from __future__ import annotations

import re
import unittest
from unittest import mock

import statusline
from tests.payloads import base
from tests.support import HOME, NOW, changed, environment, porcelain, run_main, strip_ansi, untracked

GIT = porcelain(changed(".M"), untracked(), ab="+2 -0")
ACCOUNT = "me@example.com"
A = f" • {ACCOUNT}"
MEMORY = (int(7.6 * 2**30), int(14.8 * 2**30))


def payload(**overrides) -> dict:
    data = base(NOW.timestamp(), cwd=f"{HOME}/projects/work/demo")
    data.update(overrides)
    return data


class OrderTest(unittest.TestCase):
    def test_fields_in_order_with_text_labels(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            line = run_main(payload())
        self.assertEqual(
            line,
            "~/…/demo • 5h 23.5% [14:00] • 7d 41.2% [Sun 12:00] • "
            "16k/200k 8% • Opus 5.5 (high) • 7.6GB/14.8GB • "
            "repo:main !1 ?1 ⇡2 • me@example.com",
        )

    def test_account_can_be_turned_off(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY), mock.patch.dict(statusline.CONFIG, {"show_account": False}):
            self.assertNotIn(ACCOUNT, run_main(payload()))

    def test_env_var_turns_the_account_off(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY), mock.patch.dict("os.environ", {"STATUSLINE_ACCOUNT": "0"}):
            line = run_main(payload())
        self.assertNotIn(ACCOUNT, line)
        self.assertTrue(line.endswith("repo:main !1 ?1 ⇡2"))

    def test_session_cost_is_not_shown(self):
        # A subscription: the cost would be an estimate, not a bill.
        with environment(git=GIT):
            self.assertNotIn("$", run_main(payload()))

    def test_model_without_effort_shows_alone(self):
        data = payload()
        del data["effort"]
        with environment(git=None):
            self.assertTrue(run_main(data).endswith("• Opus 5.5"))


class ShrinkTest(unittest.TestCase):
    """Narrowing the terminal one column at a time must shed detail in the
    agreed order, and only then drop whole fields: account, memory, git,
    model, cwd."""

    EXPECTED = [
        "~/…/demo • 5h 23.5% [14:00] • 7d 41.2% [Sun 12:00] • 16k/200k 8% • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2" + A,
        # 1. reset times
        "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k 8% • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2" + A,
        # 2. context's percentage
        "~/…/demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2" + A,
        # 3. cwd down to its leaf
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main !1 ?1 ⇡2" + A,
        # 4. git symbols
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 (high) • 7.6GB/14.8GB • repo:main" + A,
        # 5. effort
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • 7.6GB/14.8GB • repo:main" + A,
        # then whole fields: account, memory, git, model, cwd
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • 7.6GB/14.8GB • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • repo:main",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5",
        "demo • 5h 23.5% • 7d 41.2% • 16k/200k",
        "5h 23.5% • 7d 41.2% • 16k/200k",
    ]

    def test_shrink_sequence(self):
        seen: list[str] = []
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            for width in range(200, 19, -1):
                line = run_main(payload(), columns=width)
                if not seen or line != seen[-1]:
                    seen.append(line)
        self.assertEqual(seen, self.EXPECTED)

    def test_every_line_fits_until_only_quota_and_context_remain(self):
        floor = len(self.EXPECTED[-1])
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            for width in range(floor, 200):
                with self.subTest(width=width):
                    self.assertLessEqual(len(run_main(payload(), columns=width)), width)

    def test_quota_and_context_are_never_dropped(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            self.assertEqual(run_main(payload(), columns=20), self.EXPECTED[-1])


class WrapTest(unittest.TestCase):
    """With two lines allowed, fields move to the second line before anything
    is shed, and the one-line shrink takes over only when two lines are not
    enough."""

    FULL = ShrinkTest.EXPECTED[0]
    FIELDS = FULL.split(" • ")

    def layouts(self):
        """Each width, from wide to narrow, with the lines laid out there."""
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY, max_lines=2):
            for width in range(len(self.FULL) + 10, 19, -1):
                yield width, run_main(payload(), columns=width).split("\n")

    def fits_on_two_lines(self, width):
        """Whether the full line could be split into two lines of `width`."""
        return any(
            max(len(" • ".join(self.FIELDS[:i])), len(" • ".join(self.FIELDS[i:]))) <= width
            for i in range(1, len(self.FIELDS))
        )

    def test_wide_enough_is_one_line(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY, max_lines=2):
            self.assertEqual(run_main(payload(), columns=len(self.FULL)), self.FULL)

    def test_moves_to_a_second_line_before_shedding(self):
        for width, lines in self.layouts():
            if len(self.FULL) > width and self.fits_on_two_lines(width):
                with self.subTest(width=width):
                    self.assertEqual(len(lines), 2)
                    self.assertEqual(" • ".join(lines), self.FULL)

    def test_sheds_only_once_two_lines_are_not_enough(self):
        for width, lines in self.layouts():
            if " • ".join(lines) != self.FULL:
                with self.subTest(width=width):
                    self.assertFalse(self.fits_on_two_lines(width))

    def test_never_more_than_two_lines_and_each_fits(self):
        floor = len(ShrinkTest.EXPECTED[-1])
        for width, lines in self.layouts():
            with self.subTest(width=width):
                self.assertLessEqual(len(lines), 2)
                if width >= floor:
                    self.assertTrue(all(len(line) <= width for line in lines))

    def test_fields_keep_their_order(self):
        # Each field by the shape of its value; the directory changes as it
        # shortens, so it is whatever matches no other field.
        patterns = {"5h": r"5h ", "7d": r"7d ", "context": r"\d+k/", "model": r"Opus",
                    "memory": r"[\d.]+GB/", "git": r"repo:", "account": r"\S+@"}
        order = ["cwd"] + list(patterns)

        def field(text):
            return next((name for name, pat in patterns.items() if re.match(pat, text)), "cwd")

        for width, lines in self.layouts():
            shown = [field(f) for f in " • ".join(lines).split(" • ")]
            with self.subTest(width=width):
                self.assertEqual(shown, [f for f in order if f in shown])


def api_payload(cost=1.2345) -> dict:
    """An API-key session: no quotas, and a cost that is a bill."""
    data = payload()
    del data["rate_limits"]
    data["cost"]["total_cost_usd"] = cost
    return data


class CostTest(unittest.TestCase):
    def test_api_session_shows_its_cost_after_the_cwd(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            line = run_main(api_payload())
        self.assertEqual(
            line,
            "~/…/demo • $1.23 • 16k/200k 8% • Opus 5.5 (high) • 7.6GB/14.8GB • "
            "repo:main !1 ?1 ⇡2 • me@example.com",
        )

    def test_icon(self):
        with environment(icons=True):
            line = run_main(api_payload())
        self.assertIn(f"{statusline.ICONS['cost']} $1.23", line)

    def test_nothing_spent_yet_is_hidden(self):
        # A subscription session also lacks quotas until its first response.
        with environment():
            self.assertNotIn("$", run_main(api_payload(cost=0)))

    def test_missing_or_invalid_cost_is_hidden(self):
        for cost in (None, "free"):
            with self.subTest(cost), environment():
                self.assertNotIn("$", run_main(api_payload(cost=cost)))

    def test_never_dropped(self):
        with environment(git=GIT, account=ACCOUNT, memory=MEMORY):
            self.assertEqual(run_main(api_payload(), columns=20), "$1.23 • 16k/200k")

    def test_can_be_turned_off(self):
        with environment(), mock.patch.dict(statusline.CONFIG, {"show_cost": False}):
            self.assertNotIn("$", run_main(api_payload()))


class AgentTest(unittest.TestCase):
    def test_plain_session_has_no_agent_field(self):
        with environment():
            self.assertIsNone(statusline.agent_segment(payload()))

    def test_agent_and_worktree(self):
        data = payload(agent={"name": "reviewer"}, worktree={"name": "my-feature"})
        with environment():
            self.assertEqual(statusline.agent_segment(data), (4, ["agent reviewer worktree my-feature"]))

    def test_any_linked_git_worktree(self):
        data = payload()
        data["workspace"]["git_worktree"] = "hotfix"
        with environment():
            self.assertEqual(statusline.agent_segment(data)[1], ["worktree hotfix"])

    def test_claude_worktree_wins_over_git_worktree(self):
        data = payload(worktree={"name": "my-feature"})
        data["workspace"]["git_worktree"] = "hotfix"
        with environment():
            self.assertEqual(statusline.agent_segment(data)[1], ["worktree my-feature"])

    def test_control_characters_are_not_printed(self):
        with environment():
            self.assertEqual(statusline.agent_segment(payload(agent={"name": "re\033]0;x\007v"}))[1], ["agent re]0;xv"])

    def test_sits_after_git_and_drops_before_memory(self):
        data = payload(agent={"name": "reviewer"})
        with environment(git=GIT, memory=MEMORY):
            wide = run_main(data)
            # The widest line that has had to drop the agent.
            narrow = next(line for w in range(len(wide), 0, -1) if "reviewer" not in (line := run_main(data, columns=w)))
        self.assertTrue(wide.endswith("repo:main !1 ?1 ⇡2 • agent reviewer"))
        self.assertIn("7.6GB/14.8GB", narrow)


class FastModeTest(unittest.TestCase):
    def test_badge_follows_the_effort_level(self):
        with environment():
            self.assertEqual(statusline.model_segment(payload(fast_mode=True))[1][0], "Opus 5.5 (high) fast")

    def test_icon(self):
        icons = statusline.ICONS
        with environment(icons=True):
            line = statusline.model_segment(payload(fast_mode=True))[1][0]
        self.assertEqual(line, f"{icons['model']} Opus 5.5 (high) {icons['fast']}")

    def test_without_an_effort_level(self):
        data = payload(fast_mode=True)
        del data["effort"]
        with environment():
            variants = statusline.model_segment(data)[1]
        self.assertEqual((variants[0], variants[-1]), ("Opus 5.5 fast", "Opus 5.5"))

    def test_off_absent_or_not_a_boolean_shows_nothing(self):
        absent = payload()
        del absent["fast_mode"]
        for data in (payload(), absent, payload(fast_mode="true")):
            with self.subTest(data.get("fast_mode", "absent")), environment():
                self.assertNotIn("fast", run_main(data))

    def test_sheds_together_with_the_effort_level(self):
        data = payload(fast_mode=True)
        with environment(git=GIT, memory=MEMORY):
            lines = [run_main(data, columns=w) for w in range(200, 19, -1)]
        self.assertIn("Opus 5.5 (high) fast", lines[0])
        for line in lines:
            with self.subTest(line):
                self.assertEqual("(high)" in line, "fast" in line)


class LabelsAndColourTest(unittest.TestCase):
    def test_icons_replace_text_labels(self):
        data = payload(agent={"name": "reviewer"}, worktree={"name": "my-feature"}, fast_mode=True)
        with environment(icons=True, git=GIT, account=ACCOUNT, memory=MEMORY):
            line = run_main(data)
        for key, icon in statusline.ICONS.items():
            if key == "cost":
                continue  # API keys only, where the quotas are absent; see CostTest
            with self.subTest(key):
                self.assertIn(icon, line)
        for label in statusline.TEXT_LABELS.values():
            with self.subTest(label):
                self.assertNotIn(label, line)

    def test_env_var_turns_icons_off(self):
        with environment(icons=True, git=GIT), mock.patch.dict("os.environ", {"STATUSLINE_ICONS": "0"}):
            line = run_main(payload())
        self.assertIn("5h 23.5%", line)
        for icon in statusline.ICONS.values():
            with self.subTest(icon):
                self.assertNotIn(icon, line)

    def test_colour_on_emits_ansi(self):
        with environment(colour=True, git=GIT):
            self.assertIn("\033[", run_main(payload()))

    def test_separators_are_dim(self):
        with environment(colour=True, git=GIT):
            line = run_main(payload())
        dim_sep = f"{statusline.DIM} • {statusline.RESET}"
        self.assertEqual(line.count(dim_sep), line.count("•"))
        self.assertGreater(line.count(dim_sep), 0)

    def test_no_color_strips_every_escape(self):
        with environment(colour=False, git=GIT):
            line = run_main(payload())
        self.assertEqual(line, strip_ansi(line))

    def test_colour_does_not_change_the_fitted_width(self):
        # Escapes are invisible, so they must not count towards the width.
        with environment(colour=True, git=GIT):
            coloured = strip_ansi(run_main(payload(), columns=90))
        with environment(colour=False, git=GIT):
            plain = run_main(payload(), columns=90)
        self.assertEqual(coloured, plain)


if __name__ == "__main__":
    unittest.main()
