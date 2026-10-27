#!/usr/bin/env python3
"""Set the WSL kernel release from the actual build date, retaining KMI."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shlex


def apply(kernel, template, date, keep_kmi):
    datetime.strptime(date, "%Y%m%d")
    brand = template.replace("{date}", date)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", brand):
        raise ValueError("Invalid WSL kernel brand")
    makefile = (kernel / "Makefile").read_text()
    version = ".".join(re.search(rf"^{key}\s*=\s*(\d+)\s*$", makefile, re.M).group(1)
                       for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL"))
    constants = (kernel / "build.config.constants").read_text()
    android = re.search(r"^BRANCH=(android\d+)-", constants, re.M).group(1)
    kmi = re.search(r"^KMI_GENERATION=(\d+)\s*$", constants, re.M).group(1)
    release = f"{version}-{android}" + (f"-{kmi}" if keep_kmi else "") + f"-{brand}"
    if len(release) > 64:
        raise ValueError("Kernel release exceeds UTS_RELEASE length limit")
    script = kernel / "scripts/setlocalversion"
    lines = script.read_text().splitlines()
    if not lines[-1].startswith(("echo ", "printf ")):
        raise ValueError("Unrecognized setlocalversion final output; no changes written")
    lines[-1] = "printf '%s\\n' " + shlex.quote(release)
    script.write_text("\n".join(lines) + "\n")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--keep-kmi", choices=("true", "false"), required=True)
    args = parser.parse_args()
    release = apply(args.kernel, args.template, args.date, args.keep_kmi == "true")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write(f"EXPECTED_KERNEL_RELEASE={release}\n")
    print(f"WSL kernel release: {release}")


if __name__ == "__main__":
    main()
