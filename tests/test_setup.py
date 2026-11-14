"""The setup screen, apart from curses: the rows, the preview, and saving."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import statusline
from tests.support import environment, porcelain, strip_ansi

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("setup_screen", ROOT / "scripts" / "setup.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)


def settings(**changes) -> dict:
    """Every setting the screen manages, at its default unless changed."""
    return {**{key: setup.DEFAULTS[key] for key in setup.KEYS}, **changes}


class EditorTest(unittest.TestCase):
    def test_moves_between_settings_and_stops_at_the_ends(self):
        editor = setup.Editor(settings())
        editor.move(-1)
        self.assertEqual(editor.field[1], "show_cwd")
        editor.move(100)
        self.assertEqual(editor.field[1], "separator")

    def test_change_toggles_a_switch(self):
        editor = setup.Editor(settings())
        editor.change(1)
        self.assertFalse(editor.settings["show_cwd"])
        self.assertTrue(editor.dirty)
        editor.change(-1)
        self.assertTrue(editor.settings["show_cwd"])
        self.assertFalse(editor.dirty)

    def test_change_steps_through_choices_both_ways(self):
        editor = setup.Editor(settings())
        editor.cursor = setup.KEYS.index("separator")
        editor.change(-1)
        self.assertEqual(editor.settings["separator"], "  ")
        editor.change(1)
        self.assertEqual(editor.settings["separator"], " • ")

    def test_a_value_set_by_hand_stays_on_offer(self):
        editor = setup.Editor(settings(separator=" / "))
        editor.cursor = setup.KEYS.index("separator")
        self.assertEqual(editor.choice("separator"), "' / '")
        for _ in setup.CHOICES["separator"]:
            editor.change(1)
        self.assertNotEqual(editor.settings["separator"], " / ")
        editor.change(1)
        self.assertEqual(editor.settings["separator"], " / ")

    def test_reorder_moves_a_field_and_the_cursor_with_it(self):
        editor = setup.Editor(settings())
        editor.cursor = setup.KEYS.index("show_git")
        editor.reorder(-1)
        self.assertEqual(editor.settings["order"][:9], ["cwd", "cost", "quota", "context", "cache", "model", "output_style", "git", "memory"])
        self.assertEqual(editor.field[1], "show_git")
        self.assertTrue(editor.dirty)

    def test_rows_under_a_field_move_with_it(self):
        editor = setup.Editor(settings())
        editor.cursor = setup.KEYS.index("show_duration")
        editor.reorder(1)
        keys = [key for _, key, _ in editor.fields]
        self.assertEqual(keys[3:10], ["show_cache", "show_context", "show_input_tokens", "show_cache_split", "show_output_tokens", "show_duration", "show_lines_changed"])
        self.assertEqual(editor.field[1], "show_duration")

    def test_reorder_stops_at_the_ends_and_skips_the_look(self):
        editor = setup.Editor(settings())
        editor.reorder(-1)
        self.assertFalse(editor.dirty)
        editor.cursor = setup.KEYS.index("icons")
        editor.reorder(-1)
        self.assertFalse(editor.dirty)

    def test_opens_on_a_partial_order(self):
        editor = setup.Editor(settings(order=["git"]))
        self.assertEqual(editor.fields[0][1], "show_git")
        self.assertEqual(len(editor.settings["order"]), len(statusline.FIELDS))

    def test_saves_the_order_only_when_moved(self):
        editor = setup.Editor(settings(order=["git"]))
        self.assertNotIn("order", editor.to_save())
        editor.reorder(1)
        self.assertEqual(editor.to_save()["order"][:2], ["cwd", "git"])
        editor.reorder(-1)
        self.assertNotIn("order", editor.to_save())
        # Moved back to the usual order: no order needed.
        usual = setup.Editor(settings(order=["cost"]))
        usual.reorder(1)
        self.assertEqual(usual.to_save()["order"], [])

    def test_names_the_option_chosen(self):
        self.assertEqual(setup.Editor(settings()).choice("max_lines"), "wrap")
        self.assertEqual(setup.Editor(settings(max_lines=1)).choice("max_lines"), "drop")


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(environment(git=porcelain(), account="me@example.com", memory=(2**30, 2**32)))

    def text(self, width: int = 300, **changes) -> str:
        return strip_ansi("\n".join(setup.preview(settings(**changes), width)))

    def test_follows_the_settings(self):
        self.assertIn("Opus 5.5", self.text(icons=False))
        self.assertIn("me@example.com", self.text(icons=False))
        self.assertNotIn("Opus 5.5", self.text(icons=False, show_model=False))
        self.assertIn(statusline.ICONS["model"], self.text(icons=True))
        self.assertIn("Cold (64k)", self.text(icons=False))
        self.assertNotIn("Cold", self.text(icons=False, show_cache=False))

    def test_shows_how_a_narrow_terminal_looks(self):
        self.assertEqual(len(setup.preview(settings(icons=False), 60)), 2)
        self.assertEqual(len(setup.preview(settings(icons=False, max_lines=1), 60)), 1)

    def test_splits_colour_codes_into_runs(self):
        self.assertEqual(
            setup.runs("\033[32m23%\033[0m • x"),
            [("23%", "32"), (" • x", "0")],
        )


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.home)}))
        os.environ.pop("CLAUDE_CONFIG_DIR", None)  # restored by patch.dict on exit
        self.path = self.home / ".claude" / statusline.CONFIG_FILE

    def saved(self) -> dict:
        return json.loads(self.path.read_text())

    def test_writes_only_what_differs_from_the_defaults(self):
        self.assertTrue(setup.save(self.path, {}, settings(icons=False, max_lines=1)))
        self.assertEqual(self.saved(), {"icons": False, "max_lines": 1})

    def test_keeps_other_keys_and_drops_ones_back_at_the_default(self):
        setup.save(self.path, {"warn_at": 50, "icons": False}, settings())
        self.assertEqual(self.saved(), {"warn_at": 50})

    def test_the_defaults_need_no_file(self):
        self.assertFalse(setup.save(self.path, {}, settings()))
        self.assertFalse(self.path.exists())

    def test_writes_through_a_link(self):
        target = self.home / "dotfiles" / "plimsoll.json"
        target.parent.mkdir()
        target.write_text("{}")
        self.path.parent.mkdir()
        self.path.symlink_to(target)
        setup.save(self.path, {}, settings(icons=False))
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(json.loads(target.read_text()), {"icons": False})

    def test_saves_where_the_status_line_reads(self):
        work = self.home / ".claude-work"
        os.environ["CLAUDE_CONFIG_DIR"] = str(work)
        self.assertEqual(setup.settings_path(), work / statusline.CONFIG_FILE)
        # Without its own file, an account uses the shared one.
        self.path.parent.mkdir()
        self.path.write_text("{}")
        self.assertEqual(setup.settings_path(), self.path)

    def test_refuses_a_broken_file(self):
        self.assertEqual(setup.read_file(self.path), {})
        self.path.parent.mkdir()
        for text in ("{nope", "[]"):
            self.path.write_text(text)
            with self.assertRaises(SystemExit):
                setup.read_file(self.path)

    def test_knows_when_claude_code_already_runs_the_script(self):
        claude = self.home / ".claude" / "settings.json"
        self.assertFalse(setup.installed(claude))
        claude.parent.mkdir()
        claude.write_text("[]")
        self.assertFalse(setup.installed(claude))
        claude.write_text(json.dumps({"statusLine": {"command": "other"}}))
        self.assertFalse(setup.installed(claude))
        claude.write_text(json.dumps({"statusLine": {"command": str(ROOT / "statusline.py")}}))
        self.assertTrue(setup.installed(claude))


if __name__ == "__main__":
    unittest.main()
