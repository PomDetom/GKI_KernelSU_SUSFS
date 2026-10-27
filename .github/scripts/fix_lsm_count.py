#!/usr/bin/env python3
"""Account for the additional BBG and KSU LSM registrations in modern GKI."""
import argparse
from pathlib import Path


EXTRA = """/* Additional LSMs integrated by this build recipe. */
#if IS_ENABLED(CONFIG_BBG)
#define BBG_LSM_ENABLED 1,
#else
#define BBG_LSM_ENABLED
#endif

#if IS_ENABLED(CONFIG_KSU)
#define KSU_LSM_ENABLED 1,
#else
#define KSU_LSM_ENABLED
#endif

"""
OLD = "IPE_ENABLED)"
NEW = "IPE_ENABLED\t\t\\\n\t\tBBG_LSM_ENABLED\t\\\n\t\tKSU_LSM_ENABLED)"
MARKER = "#define __COUNT_LSMS"


def fix(path):
    if not path.exists():
        print(f"No {path}; this kernel does not use the LSM count header. Skipping.")
        return False
    text = path.read_text(encoding="utf-8")
    if "BBG_LSM_ENABLED" in text or "KSU_LSM_ENABLED" in text:
        if text.count(EXTRA) == 1 and text.count(NEW) == 1:
            print("BBG and KSU LSM capacity already accounted for.")
            return False
        raise ValueError("Unrecognized existing additional LSM count; inspect before modifying")
    if text.count(MARKER) != 1 or text.count(OLD) != 1:
        raise ValueError("Unrecognized lsm_count.h layout; no changes written")
    text = text.replace(MARKER, EXTRA + MARKER, 1).replace(OLD, NEW, 1)
    path.write_text(text, encoding="utf-8")
    print("LSM capacity now counts CONFIG_BBG and CONFIG_KSU; registration checks retained.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, default=Path("common"))
    args = parser.parse_args()
    fix(args.kernel / "include/linux/lsm_count.h")


if __name__ == "__main__":
    main()
