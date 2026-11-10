"""The settings file: where it's found, what it overrides, and what's skipped."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import statusline
from tests.payloads import base
from tests.support import HOME, NOW, environment, run_main, strip_ansi

DEFAULTS = dict(statusline.CONFIG)


class SettingsFileTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.home)}))
        os.environ.pop("CLAUDE_CONFIG_DIR", None)  # restored by patch.dict on exit
        # load_settings() writes to CONFIG; put it back after each test.
        self.enterContext(mock.patch.dict(statusline.CONFIG))

    def write(self, settings, folder: str = ".claude") -> Path:
        path = self.home / folder / statusline.CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(settings if isinstance(settings, str) else json.dumps(settings))
        return path

    def loaded(self) -> dict:
        statusline.load_settings()
        return {k: v for k, v in statusline.CONFIG.items() if DEFAULTS[k] != v}

    def test_no_file_keeps_the_defaults(self):
        self.assertIsNone(statusline.config_file())
        self.assertEqual(self.loaded(), {})

    def test_overrides_only_the_keys_it_names(self):
        self.write({"icons": False, "show_account": False, "separator": " | "})
        self.assertEqual(self.loaded(), {"icons": False, "show_account": False, "separator": " | "})

    def test_an_accounts_own_file_wins(self):
        self.write({"icons": False})
        own = self.write({"show_memory": False}, folder=".claude-work")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home / ".claude-work")
        self.assertEqual(statusline.config_file(), own)
        self.assertEqual(self.loaded(), {"show_memory": False})

    def test_an_account_without_a_file_uses_the_shared_one(self):
        shared = self.write({"icons": False})
        (self.home / ".claude-work").mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.home / ".claude-work")
        self.assertEqual(statusline.config_file(), shared)
        self.assertEqual(self.loaded(), {"icons": False})

    def test_a_broken_file_keeps_the_defaults(self):
        for text in ('{"icons": false,}', '["icons"]', "null", ""):
            with self.subTest(text):
                self.write(text)
                self.assertEqual(self.loaded(), {})

    def test_unknown_keys_are_skipped(self):
        self.write({"icon": False, "show_account": False})
        self.assertEqual(self.loaded(), {"show_account": False})

    def test_wrong_types_are_skipped(self):
        self.write({"icons": "no", "max_lines": True, "separator": 3, "warn_at": "50", "show_git": 0, "crit_at": 90})
        self.assertEqual(self.loaded(), {"crit_at": 90})

    def test_a_whole_number_does_for_a_decimal(self):
        self.write({"warn_at": 50, "git_timeout": 1})
        self.assertEqual(self.loaded(), {"warn_at": 50, "git_timeout": 1})


class RenderTest(unittest.TestCase):
    """The file read by the script itself, on the way to the line."""

    def render(self, settings: dict, **env) -> str:
        with tempfile.TemporaryDirectory() as tmp, environment(git=None, account="me@example.com", **env):
            path = Path(tmp) / statusline.CONFIG_FILE
            path.write_text(json.dumps(settings))
            # After environment(), which points config_file at nothing.
            with mock.patch.object(statusline, "config_file", return_value=path):
                data = base(NOW.timestamp(), cwd=f"{HOME}/demo")
                data["output_style"]["name"] = "Explanatory"
                return run_main(data)

    def test_turns_fields_and_icons_off(self):
        line = self.render({"icons": False, "show_account": False, "show_output_style": False}, icons=True)
        self.assertEqual(line, "~/demo • 5h 23.5% [14:00] • 7d 41.2% [Sun 12:00] • 16k/200k 8% • Opus 5.5 (high)")

    def test_no_color_still_wins(self):
        line = self.render({"colour": True})
        self.assertEqual(line, strip_ansi(line))


if __name__ == "__main__":
    unittest.main()
