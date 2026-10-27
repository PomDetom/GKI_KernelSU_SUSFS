#!/usr/bin/env python3
"""Restore the real SUSFS SELinux operations omitted from pinned SukiSU."""
import argparse
from pathlib import Path


INCLUDE = '\n#ifdef CONFIG_KSU_SUSFS\n#include "sukisu_selinux_operations.inc"\n#endif\n'
NO_PREINIT = '''/* SukiSU has no preinit runner; use its existing ksud/init boot path. */
#ifdef CONFIG_KSU_SUSFS
#define KSU_NO_PREINIT 1
#endif

'''


def integrate(common, root, asset):
    common, root, asset = Path(common), Path(root), Path(asset)
    hide = root / "feature/selinux_hide.c"
    entry = common / "fs/exec.c"
    original_hide, original_exec = hide.read_text(), entry.read_text()
    operations = asset.read_text()
    for signature in ("ssize_t my_write_context(", "ssize_t my_write_access(", "int my_setprocattr("):
        if signature not in operations:
            raise ValueError("SUSFS SELinux operations asset is incomplete")
    if "ksu_selinux_hide_running" not in original_hide:
        raise ValueError("Unknown SukiSU SELinux feature source")
    result_hide = original_hide
    if '#include "sukisu_selinux_operations.inc"' not in result_hide:
        if any(name in result_hide for name in ("my_write_context(", "my_write_access(", "my_setprocattr(")):
            raise ValueError("SukiSU already has SELinux operation implementations; inspect instead of duplicating them")
        result_hide += INCLUDE

    result_exec = original_exec
    # This SukiSU tree never implemented the optional preinit runner. The SUSFS
    # patch already provides this guard; do not manufacture successful stubs.
    if not (root / "preinit/preinit.c").exists() and NO_PREINIT not in result_exec:
        anchor = "#include "
        position = result_exec.find(anchor)
        if position == -1 or "#ifndef KSU_NO_PREINIT" not in result_exec:
            raise ValueError("Cannot verify the SUSFS preinit guard in fs/exec.c")
        result_exec = result_exec[:position] + NO_PREINIT + result_exec[position:]

    (root / "feature/sukisu_selinux_operations.inc").write_text(operations)
    if result_hide != original_hide:
        hide.write_text(result_hide)
    if result_exec != original_exec:
        entry.write_text(result_exec)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("common", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("asset", type=Path)
    args = parser.parse_args()
    try:
        integrate(args.common, args.root, args.asset)
    except (OSError, ValueError) as error:
        parser.exit(1, f"SukiSU SUSFS integration error: {error}\n")
    print("SukiSU SUSFS: backup-policy SELinux operations integrated; absent preinit runner guarded")


if __name__ == "__main__":
    main()
