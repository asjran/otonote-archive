#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
node tools/build_web_client.mjs "${1:-output/web-client-$(date -u +%Y%m%dT%H%M%SZ)}"
