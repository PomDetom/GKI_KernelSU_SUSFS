#!/usr/bin/env python3
"""Test include/optional-hook wiring; the full SELinux body needs kernel headers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from fix_sukisu_susfs import integrate, NO_PREINIT

ASSET = '''
typedef long ssize_t;
ssize_t my_write_context(void) { return 1; }
ssize_t my_write_access(void) { return 2; }
int my_setprocattr(void) { return 3; }
'''
EXEC = '''#include "empty.h"
#ifndef KSU_NO_PREINIT
extern int ksu_setup_preinit_file(void);
int main(void) { return ksu_setup_preinit_file(); }
#else
int main(void) { return 0; }
#endif
'''


class SusfsWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.common, self.root = self.directory / "common", self.directory / "root"
        (self.common / "fs").mkdir(parents=True)
        (self.root / "feature").mkdir(parents=True)
        self.hide = self.root / "feature/selinux_hide.c"
        self.entry = self.common / "fs/exec.c"
        self.hide.write_text("int ksu_selinux_hide_running;\n")
        self.entry.write_text(EXEC)
        (self.entry.parent / "empty.h").touch()
        self.asset = self.directory / "operations.inc"
        self.asset.write_text(ASSET)

    def link(self, extra=()):
        binary = self.directory / "fixture"
        subprocess.run(["clang", "-DCONFIG_KSU_SUSFS", "-Wall", "-Werror", str(self.hide), str(self.entry), *map(str, extra), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

    def test_no_backend_does_not_leave_undefined_preinit_and_repeats(self):
        integrate(self.common, self.root, self.asset)
        self.link()
        before = (self.hide.read_bytes(), self.entry.read_bytes())
        integrate(self.common, self.root, self.asset)
        self.assertEqual(before, (self.hide.read_bytes(), self.entry.read_bytes()))
        self.assertEqual(self.entry.read_text().count("#define KSU_NO_PREINIT 1"), 1)

    def test_existing_backend_is_not_disabled(self):
        preinit = self.root / "preinit/preinit.c"
        preinit.parent.mkdir()
        preinit.write_text("int ksu_setup_preinit_file(void) { return 0; }\n")
        integrate(self.common, self.root, self.asset)
        self.assertNotIn(NO_PREINIT, self.entry.read_text())
        self.link([preinit])

    def test_existing_implementation_is_not_duplicated(self):
        original = "int ksu_selinux_hide_running;\nint my_setprocattr(void) { return 7; }\n"
        self.hide.write_text(original)
        with self.assertRaises(ValueError):
            integrate(self.common, self.root, self.asset)
        self.assertEqual(self.hide.read_text(), original)
        self.assertEqual(self.entry.read_text(), EXEC)


if __name__ == "__main__":
    unittest.main()
