#!/bin/sh
# Scan the actual index by default, including values differing from the worktree.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$repo_root/tools/repository_hygiene.py" scan --root "$repo_root" "$@"
