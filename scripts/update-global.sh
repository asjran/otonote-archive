#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
# Prefer the repository's pinned Node when installed through nvm.
node_version="$(tr -d '[:space:]' < .nvmrc)"
node_bin="${NVM_DIR:-$HOME/.nvm}/versions/node/v${node_version#v}/bin"
if [[ -x "$node_bin/node" ]]; then
  export PATH="$node_bin:$PATH"
fi
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/ournotes-update-pycache}"
exec "${OURNOTES_PYTHON:-python3}" -m tools.global_update "$@"
