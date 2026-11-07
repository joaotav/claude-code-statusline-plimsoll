"""The git segment: porcelain v2 parsing, symbols, colours, and a real repo."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import statusline
from statusline import BLUE, CYAN, DIM, GREEN, MAGENTA, RED, RESET, YELLOW
from tests.support import changed, environment, porcelain, renamed, unmerged, untracked

DATA = {"cwd": "/work/repo"}


class GitSegmentTest(unittest.TestCase):
    def render(self, status, **env):
        """The segment's richest variant for canned `git status` output."""
        with environment(git=status, **env):
            seg = statusline.git_segment(DATA)
        return seg[1][0] if seg else None

    def test_clean_branch_shows_repo_and_branch_only(self):
        self.assertEqual(self.render(porcelain()), "repo:main")

    def test_each_status_code_maps_to_its_symbol(self):
        cases = {
            "worktree modified": (changed(".M"), "!1"),
            "type changed": (changed(".T"), "!1"),
            "staged modified": (changed("M."), "+1"),
            "staged new file": (changed("A."), "+1"),
            "staged and modified again": (changed("MM"), "!1 +1"),
            "deleted in worktree": (changed(".D"), "✘1"),
            "deletion staged": (changed("D."), "✘1"),
            "renamed": (renamed(), "+1"),
            "untracked": (untracked(), "?1"),
            "merge conflict": (unmerged(), "=1"),
        }
        for name, (entry, symbols) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.render(porcelain(entry)), f"repo:main {symbols}")

    def test_counts_accumulate(self):
        status = porcelain(changed(".M", "a"), changed(".M", "b"), untracked("c"))
        self.assertEqual(self.render(status), "repo:main !2 ?1")

    def test_symbols_keep_a_fixed_order(self):
        status = porcelain(untracked(), changed(".D"), changed("A."), changed(".M"), unmerged(), ab="+1 -1")
        self.assertEqual(self.render(status), "repo:main =1 !1 +1 ?1 ✘1 ⇡1 ⇣1")

    def test_ahead_and_behind(self):
        self.assertEqual(self.render(porcelain(ab="+2 -0")), "repo:main ⇡2")
        self.assertEqual(self.render(porcelain(ab="+0 -3")), "repo:main ⇣3")
        self.assertEqual(self.render(porcelain(ab="+0 -0")), "repo:main")

    def test_detached_head_shows_short_sha(self):
        status = porcelain(head="(detached)", oid="abc1234def5678")
        self.assertEqual(self.render(status), "repo:@abc1234")

    def test_control_characters_in_repo_name_are_not_printed(self):
        self.assertEqual(self.render(porcelain(), repo="re\033]0;x\007po"), "re]0;xpo:main")

    def test_unknown_repo_name_shows_branch_alone(self):
        with environment(git=porcelain(), repo=None):
            self.assertEqual(statusline.git_segment(DATA)[1], ["main"])

    def test_symbols_shed_before_the_branch(self):
        with environment(git=porcelain(untracked())):
            variants = statusline.git_segment(DATA)[1]
        self.assertEqual(variants[0], "repo:main ?1")
        self.assertEqual(variants[-1], "repo:main")

    def test_conflict_counts_only_as_a_conflict(self):
        # Deleted by them: once a conflict, not also a deletion.
        z = "0" * 40
        entry = f"u UD N... 100644 100644 000000 100644 {z} {z} {z} file"
        self.assertEqual(self.render(porcelain(entry)), "repo:main =1")

    def test_operation_and_stashes(self):
        git_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (git_dir / "rebase-merge").mkdir()
        for name, text in (("msgnum", "2"), ("end", "5"), ("head-name", "refs/heads/side")):
            (git_dir / "rebase-merge" / name).write_text(text + "\n")
        (git_dir / "logs" / "refs").mkdir(parents=True)
        (git_dir / "logs" / "refs" / "stash").write_text("a\nb\n")
        status = porcelain(unmerged(), head="(detached)")
        with environment(git=status, colour=True), mock.patch.object(statusline, "git_dirs", return_value=(git_dir, git_dir, git_dir)):
            variants = statusline.git_segment(DATA)[1]
        self.assertEqual(variants[0], f"repo:side|{YELLOW}REBASE 2/5{RESET} {RED}=1{RESET} {DIM}$2{RESET}")
        # A narrow terminal sheds the counts but keeps the operation.
        self.assertEqual(variants[-1], f"repo:side|{YELLOW}REBASE 2/5{RESET}")

    def test_no_git_output_hides_the_segment(self):
        self.assertIsNone(self.render(None))

    def test_no_cwd_hides_the_segment(self):
        with environment(git=porcelain()):
            self.assertIsNone(statusline.git_segment({}))

    def test_each_symbol_has_its_colour(self):
        status = porcelain(untracked(), changed(".D"), changed("A."), changed(".M"), unmerged(), ab="+1 -1")
        line = self.render(status, colour=True)
        for text, code in (
            ("=1", RED),
            ("!1", YELLOW),
            ("+1", GREEN),
            ("?1", BLUE),
            ("✘1", RED),
            ("⇡1", CYAN),
            ("⇣1", MAGENTA),
        ):
            with self.subTest(text):
                self.assertIn(f"{code}{text}{RESET}", line)


class GitOperationTest(unittest.TestCase):
    def setUp(self):
        self.git_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, name, text=""):
        path = self.git_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_nothing_in_progress(self):
        self.assertIsNone(statusline.git_operation(self.git_dir))

    def test_each_marker_names_its_operation(self):
        for marker, label in (
            ("MERGE_HEAD", "MERGE"),
            ("CHERRY_PICK_HEAD", "CHERRY-PICK"),
            ("REVERT_HEAD", "REVERT"),
            ("BISECT_LOG", "BISECT"),
        ):
            with self.subTest(marker):
                self.write(marker)
                self.assertEqual(statusline.git_operation(self.git_dir), (label, None))
                (self.git_dir / marker).unlink()

    def test_apply_style_rebase_and_am(self):
        self.write("rebase-apply/next", "1\n")
        self.write("rebase-apply/last", "3\n")
        self.assertEqual(statusline.git_operation(self.git_dir), ("REBASE 1/3", None))
        self.write("rebase-apply/applying")
        self.assertEqual(statusline.git_operation(self.git_dir), ("AM 1/3", None))

    def test_rebase_of_a_detached_head_names_no_branch(self):
        self.write("rebase-merge/head-name", "detached HEAD\n")
        self.assertEqual(statusline.git_operation(self.git_dir), ("REBASE", None))


@unittest.skipIf(sys.platform == "win32", "needs FIFOs")
class TrappedGitDirTest(unittest.TestCase):
    """A repo from an archive controls its .git. A file there that is not a
    regular file (a FIFO, or a link to /dev/zero) must not hang the line or
    fill memory. The traps here are FIFOs: skipped as /dev/zero would be, but
    a regression only blocks on one, where /dev/zero would eat memory."""

    def setUp(self):
        self.git_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def trap(self, name):
        path = self.git_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)

    def returns(self, call):
        """call()'s result, failing rather than hanging if it never returns."""
        result = []
        worker = threading.Thread(target=lambda: result.append(call()), daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "read did not return")
        return result[0]

    def test_trapped_stash_log(self):
        self.trap("logs/refs/stash")
        self.assertEqual(self.returns(lambda: statusline.stash_count(self.git_dir)), 0)

    def test_trapped_rebase_step(self):
        self.trap("rebase-merge/msgnum")
        self.assertEqual(self.returns(lambda: statusline.git_operation(self.git_dir)), ("REBASE", None))

    def test_trapped_commondir(self):
        work = self.git_dir / "work"
        work.mkdir()
        (work / ".git").write_text(f"gitdir: {self.git_dir}\n")
        self.trap("commondir")
        dirs = self.returns(lambda: statusline.git_dirs(str(work)))
        self.assertEqual(dirs[2], dirs[1])

    def test_trapped_dot_git_is_not_a_repo(self):
        work = self.git_dir / "work"
        work.mkdir()
        os.mkfifo(work / ".git")
        self.assertIsNone(self.returns(lambda: statusline.git_dirs(str(work))))

    def test_a_long_stash_log_is_read_only_in_part(self):
        log = self.git_dir / "logs" / "refs" / "stash"
        log.parent.mkdir(parents=True)
        log.write_bytes((b"x" * 99 + b"\n") * 20000)  # 2 MB, 20000 entries
        self.assertEqual(statusline.stash_count(self.git_dir), 2**20 // 100)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RealRepoTest(unittest.TestCase):
    """Against a real repository, so a change in git's porcelain or in how we
    call it shows up here rather than as a blank field."""

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.dir / "demo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        # Real git and repo_name here: patch only the display switches.
        self.enterContext(mock.patch.dict(statusline.CONFIG, {"icons": False, "colour": False}))

    def test_untracked_file_in_a_fresh_repo(self):
        (self.repo / "new.txt").write_text("x")
        seg = statusline.git_segment({"cwd": str(self.repo)})
        self.assertEqual(seg[1][0], "demo:main ?1")

    def test_subdirectory_names_the_repo_root(self):
        sub = self.repo / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(statusline.repo_name(str(sub)), "demo")

    def git(self, *args, cwd=None):
        subprocess.run(
            ["git", "-C", str(cwd or self.repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    def commit(self, text, message):
        (self.repo / "f").write_text(text)
        self.git("add", "f")
        self.git("commit", "-q", "-m", message)

    def test_linked_worktree_names_the_main_repo(self):
        self.commit("a", "init")
        tree = self.dir / "demo-hotfix"
        self.git("worktree", "add", "-q", str(tree), "-b", "hotfix")
        self.assertEqual(statusline.repo_name(str(tree)), "demo")
        self.assertEqual(statusline.git_segment({"cwd": str(tree)})[1][0], "demo:hotfix")

    def test_stashes_are_counted(self):
        self.commit("a", "init")
        for text in ("b", "c"):
            (self.repo / "f").write_text(text)
            self.git("stash", "-q")
        self.assertEqual(statusline.git_segment({"cwd": str(self.repo)})[1][0], "demo:main $2")

    def test_stashes_show_in_a_linked_worktree_too(self):
        self.commit("a", "init")
        (self.repo / "f").write_text("b")
        self.git("stash", "-q")
        tree = self.dir / "demo-hotfix"
        self.git("worktree", "add", "-q", str(tree), "-b", "hotfix")
        self.assertEqual(statusline.git_segment({"cwd": str(tree)})[1][0], "demo:hotfix $1")

    def test_rebase_stopped_on_a_conflict(self):
        self.commit("a", "init")
        self.git("checkout", "-q", "-b", "side")
        self.commit("side", "side")
        self.git("checkout", "-q", "main")
        self.commit("main", "main")
        self.git("checkout", "-q", "side")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("rebase", "main")
        self.assertEqual(statusline.git_segment({"cwd": str(self.repo)})[1][0], "demo:side|REBASE 1/1 =1")

    def test_merge_stopped_on_a_conflict(self):
        self.commit("a", "init")
        self.git("checkout", "-q", "-b", "side")
        self.commit("side", "side")
        self.git("checkout", "-q", "main")
        self.commit("main", "main")
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("merge", "side")
        self.assertEqual(statusline.git_segment({"cwd": str(self.repo)})[1][0], "demo:main|MERGE =1")

    def test_outside_a_repo_hides_the_segment(self):
        self.assertIsNone(statusline.git_status(str(self.dir)))
        self.assertIsNone(statusline.repo_name(str(self.dir)))

    def test_missing_directory_hides_the_segment(self):
        self.assertIsNone(statusline.git_status(str(self.dir / "nope")))

    def test_repo_config_cannot_run_an_fsmonitor_command(self):
        # A repo that arrived as an archive can carry its own .git/config.
        marker = self.dir / "ran"
        subprocess.run(["git", "-C", str(self.repo), "config", "core.fsmonitor", f"touch '{marker}'; false"], check=True)
        statusline.git_status(str(self.repo))
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
