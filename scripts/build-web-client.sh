#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  --preview) node tools/build_web_client.mjs "${2:-output/web-client-preview-$(date -u +%Y%m%dT%H%M%SZ)}" ;;
  --candidate) python3 -m tools.release_candidate --revision "${2:?commit required}" --output "${3:?output required}" ;;
  *) echo 'Usage: build-web-client.sh --preview [output] | --candidate COMMIT OUTPUT' >&2; exit 2 ;;
esac
