#!/usr/bin/env python3
"""Adapt the selected SukiSU checkout to the actual kernel header interfaces."""
import argparse
from pathlib import Path
import re


def uncomment(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def fix_sources(common, root):
    common, root = Path(common), Path(root)
    netlink = uncomment((common / "include/linux/netlink.h").read_text())
    lsm = uncomment((common / "include/linux/lsm_hooks.h").read_text())
    cfg = re.search(r"struct\s+netlink_kernel_cfg\s*\{(.*?)\};", netlink, re.S)
    if cfg is None:
        raise ValueError("Cannot locate struct netlink_kernel_cfg in the target kernel")
    files = {name: (root / name).read_text() for name in (
        "extension/kpm/super_access.c", "manager/throne_tracker.c", "hook/lsm_hook.c")}
    original = dict(files)

    if not re.search(r"\bcb_mutex\b", cfg.group(1)):
        # The table must describe real fields; inventing an offset is invalid.
        files["extension/kpm/super_access.c"] = re.sub(
            r"^DEFINE_MEMBER\(netlink_kernel_cfg, cb_mutex\)\n", "",
            files["extension/kpm/super_access.c"], flags=re.M)

    name = "manager/throne_tracker.c"
    broken = ".depth = pos->depth }\n"
    fixed = ".depth = pos->depth };\n"
    if broken in files[name]:
        if files[name].count(broken) != 1:
            raise ValueError("Unexpected manager initializer layout")
        files[name] = files[name].replace(broken, fixed, 1)
    elif fixed not in files[name]:
        raise ValueError("Cannot verify the SukiSU manager initializer")

    if re.search(r"security_add_hooks\s*\([^;]*const\s+struct\s+lsm_id\s*\*", lsm, re.S):
        name = "hook/lsm_hook.c"
        old_call = 'security_add_hooks(ksu_hooks, ARRAY_SIZE(ksu_hooks), "ksu");'
        new_call = 'security_add_hooks(ksu_hooks, ARRAY_SIZE(ksu_hooks), &ksu_lsmid);'
        declaration = '''static const struct lsm_id ksu_lsmid = {
    .name = "ksu",
    .id = LSM_ID_UNDEF,
};

'''
        anchor = "void __init ksu_lsm_hook_init(void)"
        if old_call in files[name]:
            if files[name].count(old_call) != 1 or files[name].count(anchor) != 1:
                raise ValueError("Unexpected SukiSU LSM registration layout")
            files[name] = files[name].replace(old_call, new_call, 1)
            files[name] = files[name].replace(anchor, declaration + anchor, 1)
        elif new_call not in files[name] or declaration not in files[name]:
            raise ValueError("Cannot verify the SukiSU LSM ID registration")

    # Validate every transformation before changing any of the source files.
    changed = []
    for name, text in files.items():
        if text != original[name]:
            (root / name).write_text(text)
            changed.append(name)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("common", type=Path)
    parser.add_argument("root", type=Path, help="SukiSU kernel/ directory")
    args = parser.parse_args()
    try:
        changed = fix_sources(args.common, args.root)
    except (OSError, ValueError) as error:
        parser.exit(1, f"SukiSU compatibility error: {error}\n")
    print("SukiSU compatibility: " + (", ".join(changed) if changed else "already compatible"))


if __name__ == "__main__":
    main()
