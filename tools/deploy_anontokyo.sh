#!/usr/bin/env bash

# Deploy the AnonTokyo private preview on top of the matrix release.
#
# Usage:
#   tools/deploy_anontokyo.sh [--host TARGET] [--skip-build]
#
# After running tools/deploy_site.sh, this script:
#   1. Builds output/anontokyo/site/ with PUBLIC_ANONTOKYO_ENABLED=1.
#   2. Refreshes the static player guide data + media.
#   3. Rsyncs output/anontokyo/site/anontokyo/ and output/anontokyo/site/media/anontokyo/
#      into the remote /srv/ournotes/current/.
#   4. Verifies a live HTTPS GET of the AnonTokyo home page.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${REPO_ROOT}/site"
REMOTE_ROOT="/srv/ournotes/current"
SSH_TARGET="your-server"
SKIP_BUILD=0
NODE_BIN="${NODE_BIN:-$(command -v node)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)       SSH_TARGET="${2:-}"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    -h|--help)
      printf '%s\n' "tools/deploy_anontokyo.sh [--host TARGET] [--skip-build]"
      exit 0
      ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

for cmd in rsync ssh curl; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "${cmd}" >&2
    exit 1
  fi
done

SSH_OPTIONS=(
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
)

run_ssh() { ssh "${SSH_OPTIONS[@]}" "${SSH_TARGET}" "$@"; }

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  if [[ ! -f "${REPO_ROOT}/output/anontokyo-catalog.json" ]]; then
    printf 'Missing output/anontokyo-catalog.json; run npm run refresh:anontokyo locally first.\n' >&2
    exit 1
  fi
  printf 'Refreshing AnonTokyo static data...\n'
  (cd "${REPO_ROOT}" && python3 tools/anontokyo_refresh_static.py)

  printf 'Building site/dist with PUBLIC_ANONTOKYO_ENABLED=1...\n'
  (cd "${SITE_DIR}" && npm run build:anontokyo)
fi

DIST_DIR="${REPO_ROOT}/output/anontokyo/site"
if [[ ! -f "${DIST_DIR}/anontokyo/index.html" ]]; then
  printf 'Build output is missing %s/anontokyo/index.html\n' "${DIST_DIR}" >&2
  exit 1
fi

printf 'Rsyncing private-preview to %s:%s...\n' "${SSH_TARGET}" "${REMOTE_ROOT}"
rsync -az --delete \
  -e "ssh ${SSH_OPTIONS[*]}" \
  "${DIST_DIR}/anontokyo/" \
  "${SSH_TARGET}:${REMOTE_ROOT}/anontokyo/"

printf 'Rsyncing new _astro assets (additive, no --delete) to %s:%s/_astro/...\n' "${SSH_TARGET}"
rsync -az \
  -e "ssh ${SSH_OPTIONS[*]}" \
  "${DIST_DIR}/_astro/" \
  "${SSH_TARGET}:${REMOTE_ROOT}/_astro/"

printf 'Rsyncing media/anontokyo to %s:%s...\n' "${SSH_TARGET}" "${REMOTE_ROOT}"
rsync -az \
  -e "ssh ${SSH_OPTIONS[*]}" \
  "${DIST_DIR}/media/anontokyo/" \
  "${SSH_TARGET}:${REMOTE_ROOT}/media/anontokyo/"

printf 'Rsyncing media index (data/anontokyo-player-guide) to %s:%s/media-index/...\n' "${SSH_TARGET}" "${REMOTE_ROOT}"
run_ssh "mkdir -p ${REMOTE_ROOT}/_data/anontokyo-player-guide"
rsync -az \
  -e "ssh ${SSH_OPTIONS[*]}" \
  "${SITE_DIR}/src/data/anontokyo-player-guide/" \
  "${SSH_TARGET}:${REMOTE_ROOT}/_data/anontokyo-player-guide/"

remote_domain="$(run_ssh 'awk "/server_name/ {print \$2; exit}" /etc/nginx/conf.d/ournotes.conf | tr -d ";"')"
if [[ -z "${remote_domain}" || "${remote_domain}" == *'$'* ]]; then
  remote_domain="otonote.example.com"
fi

printf 'Health check: https://%s/anontokyo/ (run on remote host)\n' "${remote_domain}"
healthy=0
for attempt in $(seq 1 30); do
  if run_ssh "curl -fsS --max-time 10 --resolve ${remote_domain}:443:127.0.0.1 https://${remote_domain}/anontokyo/ -o /dev/null" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done

if [[ "${healthy}" -ne 1 ]]; then
  printf 'Health check failed.\n' >&2
  exit 1
fi

printf 'Published AnonTokyo private preview to https://%s/anontokyo/\n' "${remote_domain}"