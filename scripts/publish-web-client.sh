#!/usr/bin/env bash
# Production values come only from an owner-readable config outside the checkout.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m tools.deploy_code "$@"
