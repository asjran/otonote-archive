#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_ROOT="$REPO_ROOT/output/release-builds/global-production-current/site"
CONTRACT_PATH="$REPO_ROOT/config/performance/gates.product-v1.json"
BASELINE_PATH="$REPO_ROOT/output/readiness/global-browser-baseline.json"
BROWSER_OUTPUT="$REPO_ROOT/output/readiness/performance-browser.json"
CURVE_OUTPUT="$REPO_ROOT/output/readiness/performance-load-curve.json"
REGRESSION_OUTPUT="$REPO_ROOT/output/readiness/browser-regression.json"
RUNNER_ID="${PERF_RUNNER:-}"
NODE_BIN="${PERF_NODE_BIN:-node}"
PYTHON_BIN="${PERF_PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist) DIST_ROOT="$2"; shift 2 ;;
    --contract) CONTRACT_PATH="$2"; shift 2 ;;
    --baseline) BASELINE_PATH="$2"; shift 2 ;;
    --browser-output) BROWSER_OUTPUT="$2"; shift 2 ;;
    --curve-output) CURVE_OUTPUT="$2"; shift 2 ;;
    --regression-output) REGRESSION_OUTPUT="$2"; shift 2 ;;
    --runner) RUNNER_ID="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -d "$DIST_ROOT" ]]; then
  echo "site matrix artifact is missing: $DIST_ROOT" >&2
  exit 2
fi
if [[ ! -f "$CONTRACT_PATH" ]]; then
  echo "performance contract is missing: $CONTRACT_PATH" >&2
  exit 2
fi
if [[ ! -f "$BASELINE_PATH" ]]; then
  echo "frozen browser baseline is missing: $BASELINE_PATH" >&2
  exit 2
fi
if [[ -z "$RUNNER_ID" ]]; then
  echo "fixed performance runner id is required" >&2
  exit 2
fi

mkdir -p \
  "$(dirname "$BROWSER_OUTPUT")" \
  "$(dirname "$CURVE_OUTPUT")" \
  "$(dirname "$REGRESSION_OUTPUT")"
rm -f "$BROWSER_OUTPUT" "$CURVE_OUTPUT" "$REGRESSION_OUTPUT"

GATE_TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ournotes-performance-gate.XXXXXX")"
READY_FILE="$GATE_TEMP_ROOT/port"
SERVER_LOG="$GATE_TEMP_ROOT/server.log"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$GATE_TEMP_ROOT"
}
trap cleanup EXIT INT TERM

"$PYTHON_BIN" -u -c '
import functools
import http.server
import pathlib
import sys

dist_root, ready_file = sys.argv[1:]
handler = functools.partial(
    http.server.SimpleHTTPRequestHandler,
    directory=dist_root,
)
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
pathlib.Path(ready_file).write_text(str(server.server_port), encoding="utf-8")
server.serve_forever()
' "$DIST_ROOT" "$READY_FILE" >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 100); do
  if [[ -s "$READY_FILE" ]]; then
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "isolated performance server exited before readiness" >&2
    cat "$SERVER_LOG" >&2
    exit 1
  fi
  sleep 0.05
done
if [[ ! -s "$READY_FILE" ]]; then
  echo "isolated performance server readiness timed out" >&2
  cat "$SERVER_LOG" >&2
  exit 1
fi

BASE_URL="http://127.0.0.1:$(cat "$READY_FILE")"
BROWSER_BASE_URL="$BASE_URL" \
  BROWSER_OUTPUT="$REGRESSION_OUTPUT" \
  BROWSER_DIST_ROOT="$DIST_ROOT" \
  "$NODE_BIN" "$REPO_ROOT/tools/browser_regression.cjs"

PERF_BASE_URL="$BASE_URL" PERF_RUNNER="$RUNNER_ID" \
  "$NODE_BIN" "$REPO_ROOT/tools/performance_browser.cjs" \
    --budget-only \
    --contract "$CONTRACT_PATH" \
    --baseline "$BASELINE_PATH" \
    --output "$BROWSER_OUTPUT"

"$PYTHON_BIN" "$REPO_ROOT/tools/http_load_curve.py" \
  --base-url "$BASE_URL" \
  --contract "$CONTRACT_PATH" \
  --server "python-threading-http.server" \
  --output "$CURVE_OUTPUT"
