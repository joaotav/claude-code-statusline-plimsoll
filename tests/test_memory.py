"""The memory field: parsing each platform's figures, sizes, and the text."""

from __future__ import annotations

import sys
import unittest

import statusline
from statusline import GREEN, RED, RESET
from tests.support import environment

GIB = 2**30

MEMINFO = """\
MemTotal:       16000000 kB
MemFree:         1000000 kB
MemAvailable:    6000000 kB
Buffers:          200000 kB
Cached:          4000000 kB
"""

# vm_stat as macOS prints it, trimmed; the quoted key is real.
VM_STAT = """\
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12345.
Pages active:                            200000.
Pages inactive:                          190000.
Pages wired down:                         80000.
Pages purgeable:                          10000.
"Translation faults":                 123456789.
File-backed pages:                       150000.
Anonymous pages:                         240000.
Pages occupied by compressor:            100000.
"""


class ParseTest(unittest.TestCase):
    def test_meminfo_used_is_total_minus_available(self):
        used, total = statusline.parse_meminfo(MEMINFO)
        self.assertEqual(total, 16000000 * 1024)
        self.assertEqual(used, (16000000 - 6000000) * 1024)

    def test_meminfo_without_available_is_none(self):
        self.assertIsNone(statusline.parse_meminfo("MemTotal: 100 kB\n"))

    def test_vm_stat_counts_app_wired_and_compressed(self):
        used, total = statusline.parse_vm_stat(VM_STAT, 16 * GIB)
        # (anonymous - purgeable) + wired + compressor, in 16 KiB pages.
        self.assertEqual(used, (240000 - 10000 + 80000 + 100000) * 16384)
        self.assertEqual(total, 16 * GIB)

    def test_vm_stat_missing_fields_is_none(self):
        self.assertIsNone(statusline.parse_vm_stat("Pages free: 1.\n", 16 * GIB))


class SizeTest(unittest.TestCase):
    def test_units(self):
        cases = {
            512 * 2**20: "512MB",
            8 * GIB: "8GB",
            int(7.6 * GIB): "7.6GB",
            int(14.8 * GIB): "14.8GB",
        }
        for n, expected in cases.items():
            with self.subTest(expected):
                self.assertEqual(statusline.fmt_size(n), expected)


class SegmentTest(unittest.TestCase):
    def render(self, reading, **env):
        with environment(memory=reading, **env):
            seg = statusline.memory_segment()
        return seg[1] if seg else None

    def test_used_over_total(self):
        self.assertEqual(self.render((int(7.6 * GIB), int(14.8 * GIB))), ["7.6GB/14.8GB"])

    def test_no_reading_hides_the_field(self):
        self.assertIsNone(self.render(None))

    def test_used_takes_the_usage_colours(self):
        self.assertIn(f"{GREEN}4GB{RESET}/16GB", self.render((4 * GIB, 16 * GIB), colour=True)[0])
        self.assertIn(f"{RED}14.4GB{RESET}/16GB", self.render((int(14.4 * GIB), 16 * GIB), colour=True)[0])

    def test_critical_is_marked_without_colour(self):
        self.assertEqual(self.render((int(14.4 * GIB), 16 * GIB)), ["14.4GB/16GB ⚠"])


class RealSystemTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux") or sys.platform == "darwin", "Linux and macOS only")
    def test_real_figures(self):
        """This platform's real reading; CI runs it on both Linux and macOS."""
        used, total = statusline.memory_reading()
        self.assertGreater(total, 0)
        self.assertTrue(0 < used <= total)


if __name__ == "__main__":
    unittest.main()
