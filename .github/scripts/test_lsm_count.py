#!/usr/bin/env python3
"""Check capacity expansion with a C compiler and unchanged legacy handling."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("fix_lsm_count", Path(__file__).with_name("fix_lsm_count.py"))
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)

# Same trailing-comma counting convention as GKI lsm_count.h / args.h.
HEADER = """#define __COUNT_ARGS(_0, _1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11, _12, _13, _14, _15, _n, X...) _n
#define COUNT_ARGS(X...) __COUNT_ARGS(, ##X, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
#define IS_ENABLED(config) (config)
#if CONFIG_SECURITY
#if CONFIG_SECURITY_IPE
#define IPE_ENABLED 1,
#else
#define IPE_ENABLED
#endif
#define __COUNT_LSMS(skipped_arg, args...) COUNT_ARGS(args...)
#define COUNT_LSMS(args...) __COUNT_LSMS(args)
#define MAX_LSM_COUNT COUNT_LSMS(1, 1, IPE_ENABLED)
#else
#define MAX_LSM_COUNT 0
#endif
"""


class LsmCountTests(unittest.TestCase):
    def test_enabled_disabled_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = root / "lsm_count.h"
            header.write_text(HEADER)
            FIX.fix(header)
            for security in (0, 1):
                for ipe in (0, 1):
                    for bbg in (0, 1):
                        for ksu in (0, 1):
                            expected = 2 + ipe + bbg + ksu if security else 0
                            source = '#include "lsm_count.h"\n_Static_assert(MAX_LSM_COUNT == %d, "wrong capacity");\n' % expected
                            subprocess.run(["cc", "-x", "c", "-fsyntax-only", "-I", str(root),
                                            f"-DCONFIG_SECURITY={security}", f"-DCONFIG_SECURITY_IPE={ipe}",
                                            f"-DCONFIG_BBG={bbg}", f"-DCONFIG_KSU={ksu}", "-"],
                                           input=source, text=True, check=True, capture_output=True)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lsm_count.h"
            path.write_text(HEADER)
            self.assertTrue(FIX.fix(path))
            first = path.read_bytes()
            self.assertFalse(FIX.fix(path))
            self.assertEqual(first, path.read_bytes())

    def test_unknown_layout_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lsm_count.h"
            for content in (HEADER.replace("IPE_ENABLED)", "OTHER_ENABLED)"), HEADER + "\n#define KSU_LSM_ENABLED 1,\n"):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    FIX.fix(path)
                self.assertEqual(content, path.read_text())

    def test_legacy_header_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lsm_count.h"
            self.assertFalse(FIX.fix(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
