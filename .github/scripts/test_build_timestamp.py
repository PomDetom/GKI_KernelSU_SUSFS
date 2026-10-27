#!/usr/bin/env python3
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).with_name("build_timestamp.py")
SPEC = importlib.util.spec_from_file_location("build_timestamp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TimestampTests(unittest.TestCase):
    def test_utc_time_and_shanghai_date_use_same_instant(self):
        metadata = MODULE.values(1793118600)  # 2026-10-27 16:30 UTC
        self.assertEqual(metadata["KBUILD_BUILD_TIMESTAMP"], "Tue Oct 27 16:30:00 UTC 2026")
        self.assertEqual(metadata["BUILD_DATE"], "20261028")

    def test_refreshes_stale_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "env"
            env = dict(os.environ, GITHUB_ENV=str(output), SOURCE_DATE_EPOCH="0")
            before = int(time.time())
            subprocess.run(["python3", str(SCRIPT)], env=env, check=True, capture_output=True)
            metadata = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertGreaterEqual(int(metadata["SOURCE_DATE_EPOCH"]), before)
            self.assertLessEqual(int(metadata["SOURCE_DATE_EPOCH"]), int(time.time()))

    def test_rejects_epoch_zero(self):
        with self.assertRaises(ValueError):
            MODULE.values(0)


if __name__ == "__main__":
    unittest.main()
