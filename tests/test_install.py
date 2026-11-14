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


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.dir / ".claude" / "settings.json"
        self.ours = self.dir / ".claude" / install.CONFIG_FILE
        self.enterContext(redirect_stdout(io.StringIO()))

    def write(self, settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(settings if isinstance(settings, str) else json.dumps(settings))

    def read(self):
        return json.loads(self.path.read_text())

    def backups(self) -> list[Path]:
        return sorted(self.path.parent.glob("settings.json.bak.*"))

    def test_removes_the_block_and_keeps_the_rest(self):
        self.write({"model": "opus", "statusLine": BLOCK})
        self.assertTrue(install.uninstall(self.path))
        self.assertEqual(self.read(), {"model": "opus"})
        self.assertEqual(len(self.backups()), 1)

    def test_leaves_a_different_status_line_alone(self):
        other = {"statusLine": {"type": "command", "command": "~/other.sh"}}
        self.write(other)
        self.assertFalse(install.uninstall(self.path))
        self.assertEqual(self.read(), other)
        self.assertEqual(self.backups(), [])

    def test_nothing_to_remove(self):
        self.assertTrue(install.uninstall(self.path))
        self.assertFalse(self.path.exists())
        self.write({"model": "opus"})
        self.assertTrue(install.uninstall(self.path))
        self.assertEqual(self.read(), {"model": "opus"})
        self.assertEqual(self.backups(), [])

    def test_invalid_json_is_left_alone(self):
        self.write('{"statusLine": ')
        with self.assertRaises(SystemExit):
            install.uninstall(self.path)
        self.assertEqual(self.path.read_text(), '{"statusLine": ')

    def test_offers_to_delete_the_settings_file(self):
        self.write({"statusLine": BLOCK})
        self.ours.write_text('{"icons": false}')
        install.uninstall(self.path, ask=mock.Mock(return_value=False))
        self.assertTrue(self.ours.exists())
        install.uninstall(self.path, ask=mock.Mock(return_value=True))
        self.assertFalse(self.ours.exists())

    def test_asks_nothing_without_a_settings_file(self):
        self.write({"statusLine": BLOCK})
        ask = mock.Mock()
        install.uninstall(self.path, ask=ask)
        ask.assert_not_called()

    def test_only_touches_its_own_config_folder(self):
        # An account folder: the shared file in .claude must survive.
        self.write({})
        self.ours.write_text("{}")
        work = self.dir / ".claude-work" / "settings.json"
        work.parent.mkdir()
        work.write_text(json.dumps({"statusLine": BLOCK}))
        ask = mock.Mock(return_value=True)
        install.uninstall(work, ask=ask)
        ask.assert_not_called()
        self.assertTrue(self.ours.exists())
        self.assertEqual(json.loads(work.read_text()), {})

    def test_a_linked_file_stays_a_link(self):
        target = self.dir / "dotfiles" / "settings.json"
        target.parent.mkdir()
        target.write_text(json.dumps({"statusLine": BLOCK}))
        self.path.parent.mkdir()
        self.path.symlink_to(target)
        self.ours.write_text("{}")
        install.uninstall(self.path, ask=mock.Mock(return_value=True))
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(json.loads(target.read_text()), {})
        self.assertFalse(self.ours.exists())


if __name__ == "__main__":
    unittest.main()
