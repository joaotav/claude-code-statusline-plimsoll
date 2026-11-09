"""The install script: merging the statusLine block into settings.json."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("install", ROOT / "scripts" / "install.py")
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)

BLOCK = {"type": "command", "command": str(ROOT / "statusline.py"), "padding": 0, "refreshInterval": 60}


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.dir / ".claude" / "settings.json"
        self.enterContext(redirect_stdout(io.StringIO()))

    def write(self, settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(settings if isinstance(settings, str) else json.dumps(settings))

    def read(self):
        return json.loads(self.path.read_text())

    def backups(self) -> list[Path]:
        return sorted(self.path.parent.glob("settings.json.bak.*"))

    def test_creates_the_file_and_its_folder(self):
        self.assertTrue(install.install(self.path))
        self.assertEqual(self.read(), {"statusLine": BLOCK})
        self.assertEqual(self.backups(), [])

    def test_keeps_every_other_setting(self):
        self.write({"model": "opus", "permissions": {"allow": ["Bash(ls)"]}})
        install.install(self.path)
        self.assertEqual(self.read(), {"model": "opus", "permissions": {"allow": ["Bash(ls)"]}, "statusLine": BLOCK})

    def test_backs_up_the_old_file_as_it_was(self):
        old = '{\n    "model": "opus"\n}'
        self.write(old)
        install.install(self.path)
        [backup] = self.backups()
        self.assertEqual(backup.read_text(), old)

    def test_empty_file_counts_as_no_settings(self):
        self.write("")
        install.install(self.path)
        self.assertEqual(self.read(), {"statusLine": BLOCK})

    def test_invalid_json_is_left_alone(self):
        for text in ('{"model": "opus",}', "[1, 2]"):
            with self.subTest(text):
                self.write(text)
                with self.assertRaises(SystemExit):
                    install.install(self.path)
                self.assertEqual(self.path.read_text(), text)
                self.assertEqual(self.backups(), [])

    def test_asks_before_replacing_another_status_line(self):
        other = {"type": "command", "command": "~/other.sh"}
        self.write({"statusLine": other})
        ask = mock.Mock(return_value=False)
        self.assertFalse(install.install(self.path, ask=ask))
        ask.assert_called_once()
        self.assertEqual(self.read(), {"statusLine": other})
        self.assertEqual(self.backups(), [])

        ask.return_value = True
        self.assertTrue(install.install(self.path, ask=ask))
        self.assertEqual(self.read(), {"statusLine": BLOCK})
        self.assertEqual(len(self.backups()), 1)

    def test_a_second_run_changes_nothing(self):
        self.write({"model": "opus"})
        install.install(self.path)
        before = self.path.read_text()
        ask = mock.Mock()
        self.assertTrue(install.install(self.path, ask=ask))
        ask.assert_not_called()
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(len(self.backups()), 1)

    def test_keeps_the_file_mode(self):
        self.write({})
        self.path.chmod(0o600)
        install.install(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_a_linked_file_stays_a_link(self):
        target = self.dir / "dotfiles" / "settings.json"
        target.parent.mkdir()
        target.write_text('{"model": "opus"}')
        self.path.parent.mkdir()
        self.path.symlink_to(target)
        install.install(self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(json.loads(target.read_text()), {"model": "opus", "statusLine": BLOCK})

    def test_settings_path_follows_the_config_dir(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(install.settings_path(), Path("/home/tester/.claude/settings.json"))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/home/tester/.claude-work"}):
            self.assertEqual(install.settings_path(), Path("/home/tester/.claude-work/settings.json"))


if __name__ == "__main__":
    unittest.main()
