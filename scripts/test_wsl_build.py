#!/usr/bin/env python3
"""Focused local-runner tests; fixture Images are not kernel build evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

import wsl_build as local


class LocalBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "tmp").mkdir()
        (self.workspace / "kernel/common/arch/arm64/configs").mkdir(parents=True)
        (self.workspace / "kernel/common/arch/arm64/configs/gki_defconfig").write_text("# CONFIG_KSU_SUSFS is not set\n")
        (self.workspace / "AnyKernel3").mkdir()
        self.args = argparse.Namespace(command="build", profile=local.REPO / "profiles/wsl-android16-6.12.json",
                                       workspace=self.workspace, cache=Path(self.temporary.name) / "cache",
                                       jobs=4, resume_prepare=False)
        self.build = local.LocalBuild(self.args)

    def test_nested_real_susfs_config_and_action_outputs(self):
        self.build.run_steps([{"uses": "./.github/actions/susfs-config"}], self.build.inputs)
        text = (self.workspace / "kernel/common/arch/arm64/configs/gki_defconfig").read_text()
        self.assertEqual(text.count("CONFIG_KSU_SUSFS=y"), 1)
        self.assertIn("CONFIG_KSU_SUSFS_SUS_MAP=y", text)
        results = self.build.run_steps([{"id": "extract", "uses": "./.github/actions/extract-sublevel-file-name",
                                        "with": self.build.inputs}], self.build.inputs)
        self.assertEqual(results["extract"]["outputs"]["sublevel"], "69")
        self.assertEqual(self.build.exports["FILE_NAME"], "6.12.69-android16-2026-03-SukiSU-Ultra")

    def test_environment_multiline_and_hyphenated_outputs(self):
        result = self.build.run_steps([{"id": "test-id", "run": '''
printf 'LOCAL_TEST<<END\nline1\nline2\nEND\n' >> "$GITHUB_ENV"
printf 'commit=abc\n' >> "$GITHUB_OUTPUT"
'''}, {"run": 'test "$LOCAL_TEST" = $\'line1\\nline2\''}], self.build.inputs)
        context = self.build.context(self.build.inputs, local.REPO, result)
        self.assertEqual(local.expression("steps.test-id.outputs.commit", context), "abc")
        self.assertTrue(local.expression("!contains(inputs.feature_set, 'Perf') && inputs.root_flavor == 'sukisu-ultra'", context))
        with self.assertRaises(ValueError):
            self.build.run_steps([{"uses": "actions/checkout@v7"}], self.build.inputs)

    def make_bazel_fixture(self):
        kernel = self.workspace / "kernel"
        (kernel / "common/build.config.gki").write_text("check_defconfig\n")
        (kernel / "common/BUILD.bazel").write_text('kernel_build(\n    name = "kernel_aarch64",\n)\n')
        (kernel / "tools").mkdir()
        tool = kernel / "tools/bazel"
        tool.write_text('''#!/bin/bash
set -eu
printf '%s\\n' "$@" >> arguments.log
if test -f fail-build; then exit 17; fi
mkdir -p bazel-bin/common/kernel_aarch64 bazel-bin/common/kernel_aarch64_config/out_dir
printf 'fixture Image, not a kernel\\n' > bazel-bin/common/kernel_aarch64/Image
cat > bazel-bin/common/kernel_aarch64_config/out_dir/.config <<'EOF'
CONFIG_KSU=y
CONFIG_KSU_SUSFS=y
CONFIG_ARM64_4K_PAGES=y
# CONFIG_ARM64_16K_PAGES is not set
EOF
''')
        tool.chmod(0o755)
        self.build.exports.update(FILE_NAME="fixture", KERNEL_SOURCE_COMMIT=self.build.profile["kernel_commit"])
        self.build.env.update(ROOT_IMPLEMENTATION="sukisu-ultra", SUSFS_COMMIT=self.build.inputs["susfs_commit"])
        self.build.save(synced=True, prepared=True)

    def test_repeat_build_and_failure_does_not_package_old_image(self):
        self.make_bazel_fixture()
        self.build.build()
        self.build.build()
        kernel = self.workspace / "kernel"
        self.assertEqual((kernel / "common/BUILD.bazel").read_text().count('check_defconfig = "disabled"'), 1)
        arguments = (kernel / "arguments.log").read_text()
        self.assertIn("--make_jobs=4", arguments)
        self.assertIn("--jobs=4", arguments)
        self.assertIn("--disk_cache=" + str(self.build.cache / "bazel"), arguments)
        self.build.package()
        archive = self.workspace / "dist/fixture-AnyKernel3.zip"
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.read("Image"), b"fixture Image, not a kernel\n")
        (kernel / "fail-build").touch()
        with self.assertRaises(subprocess.CalledProcessError):
            self.build.build()
        with self.assertRaises(ValueError):
            self.build.package()
        self.assertFalse(json.loads(self.build.state_file.read_text())["built"])

    def test_prepare_skip_resume_and_profile_change(self):
        self.build.save(synced=True, prepared=True)
        self.build.prepare()
        self.assertFalse(self.build.state.get("prepare_started", False))
        self.build.save(prepared=False, prepare_started=True)
        with self.assertRaises(ValueError):
            self.build.prepare()
        modified = dict(self.build.profile)
        modified["kernel_commit"] = "0" * 40
        profile = Path(self.temporary.name) / "changed.json"
        profile.write_text(json.dumps(modified))
        self.args.profile = profile
        with self.assertRaises(ValueError):
            local.LocalBuild(self.args)


if __name__ == "__main__":
    unittest.main()
