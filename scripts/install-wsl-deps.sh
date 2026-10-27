#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo "Run this script inside Ubuntu / WSL2." >&2
  exit 2
fi
ROOT_CMD=()
if [[ "$EUID" != 0 ]]; then ROOT_CMD=(sudo); fi
"${ROOT_CMD[@]}" apt-get update
"${ROOT_CMD[@]}" apt-get install -y build-essential clang lld llvm bc bison flex \
  libssl-dev libelf-dev libncurses-dev zlib1g-dev libdw-dev libzstd-dev dwarves \
  ccache cmake ninja-build pkg-config rsync unzip zip xz-utils cpio curl wget \
  file lz4 zstd jq kmod patch gnupg python3-yaml python3-venv ca-certificates
echo "Dependencies installed. Run scripts/wsl-build doctor as your normal user."
