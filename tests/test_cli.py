"""End to end: the script as Claude Code runs it, a separate process with the
payload on stdin. A raise there would blank the status line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from tests.payloads import ROOT, all_payloads

SCRIPT = ROOT / "statusline.py"


def run(stdin: str, columns: int = 120) -> subprocess.CompletedProcess:
    # An empty config dir and home, so the developer's own login and settings
    # (read from ~/.claude when the config dir has none) never show up here.
    with tempfile.TemporaryDirectory() as config_dir:
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=stdin,
            capture_output=True,
            text=True,
            env={**os.environ, "COLUMNS": str(columns), "CLAUDE_CONFIG_DIR": config_dir, "HOME": config_dir},
            timeout=10,
        )


class CliTest(unittest.TestCase):
    def test_every_payload_renders_without_error(self):
        for name, data in all_payloads(time.time()).items():
            for columns in (40, 80, 200):
                with self.subTest(name, columns=columns):
                    result = run(json.dumps(data), columns)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stderr, "")
                    self.assertNotIn("usage unavailable", result.stdout)

    def test_wraps_onto_two_lines_by_default(self):
        # The shipped config, not a patched one: wrap, and never past two lines.
        full = json.dumps(all_payloads(time.time())["full"])
        for columns in (80, 100):
            with self.subTest(columns=columns):
                self.assertEqual(len(run(full, columns).stdout.splitlines()), 2)
        for columns in range(20, 260, 7):
            with self.subTest(columns=columns):
                self.assertLessEqual(len(run(full, columns).stdout.splitlines()), 2)

    def test_empty_stdin_shows_at_most_system_memory(self):
        # Memory is the one field that needs no payload; nothing else may show.
        result = run("")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("•", result.stdout)
        self.assertNotIn("%", result.stdout)

    def test_invalid_json_degrades_to_a_marker(self):
        result = run("{not json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage unavailable", result.stdout)

    def test_non_object_json_shows_at_most_system_memory(self):
        result = run("[1, 2, 3]")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("•", result.stdout)
        self.assertNotIn("%", result.stdout)


if __name__ == "__main__":
    unittest.main()
