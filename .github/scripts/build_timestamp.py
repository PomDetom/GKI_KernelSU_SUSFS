#!/usr/bin/env python3
"""Export one current build instant for legacy Kbuild and stamped Kleaf."""
from datetime import datetime, timezone
from pathlib import Path
import os
import time
from zoneinfo import ZoneInfo


def values(epoch):
    if epoch <= 0:
        raise ValueError("Build epoch must be positive")
    instant = datetime.fromtimestamp(epoch, timezone.utc)
    return {
        "SOURCE_DATE_EPOCH": str(epoch),
        "KBUILD_BUILD_TIMESTAMP": instant.strftime("%a %b %d %H:%M:%S UTC %Y"),
        "BUILD_DATE": instant.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"),
    }


def main():
    # Refresh for each actual compilation, including prepared WSL workspaces.
    # An inherited SOURCE_DATE_EPOCH may be a stale value from preparation.
    metadata = values(int(time.time()))
    text = "".join(f"{key}={value}\n" for key, value in metadata.items())
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
