#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${REPO_ROOT}/site"
DIST_DIR="${OURNOTES_DIST_DIR:-${REPO_ROOT}/output/release-builds/global-production-current/site}"
PACKAGE_LOCK="${OURNOTES_PACKAGE_LOCK:-${SITE_DIR}/package-lock.json}"
RELEASE_INDEX="${OURNOTES_RELEASE_INDEX:-${DIST_DIR}/global/zh-CN/data/release-index.json}"
MEDIA_INDEX="${OURNOTES_MEDIA_INDEX:-${DIST_DIR}/global/zh-CN/data/media-index.json}"
DEPLOY_DIR="${REPO_ROOT}/deploy"
REMOTE_ROOT="/srv/ournotes"

COMMAND="deploy"
SSH_TARGET="your-server"
SITE_DOMAIN="otonote.example.com"
SKIP_BUILD=0
KEEP_RELEASES=2
DOCKER_IMAGE="${OURNOTES_WORKER_IMAGE:-}"
DEPLOY_STARTED_EPOCH="$(date +%s)"
BUILD_SECONDS=0
TEST_SECONDS=0
RESOURCE_SECONDS=0
MATRIX_SECONDS=0
BUDGET_SECONDS=0
MANIFEST_SECONDS=0
DISK_CHECK_SECONDS=0
ARTIFACT_DIFF_SECONDS=0
TRANSFER_SECONDS=0
ACTIVATE_SECONDS=0
HEALTH_SECONDS=0
DISK_AVAILABLE_KB=0
RSYNC_TRANSFERRED_FILES=0
RSYNC_MATCHED_FILES=0
ATTEMPT_ID="$(date -u +%Y%m%dt%H%M%Sz)-$$"
ATTEMPT_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEPLOYMENT_EVENT_LOG="${OURNOTES_DEPLOYMENT_EVENT_LOG:-${REPO_ROOT}/output/deployment-events.jsonl}"
CURRENT_PHASE="preflight"
REASON_CODE="phase_failed"
EVENT_FINALIZED=0
REMOTE_EVENTS_READY=0
release_id="unknown"
git_commit="unknown"

usage() {
  printf '%s\n' \
    "Usage:" \
    "  tools/deploy_site.sh [deploy] [options]" \
    "  tools/deploy_site.sh rollback [options]" \
    "" \
    "Options:" \
    "  --host TARGET       SSH target or config alias (default: ${SSH_TARGET})" \
    "  --domain DOMAIN     Public domain (default: ${SITE_DOMAIN})" \
    "  --skip-build        Reuse the existing Global production candidate" \
    "  --docker-image REF  Worker image recorded in SiteRelease manifest" \
    "  --keep NUMBER       Number of releases to retain (default: ${KEEP_RELEASES})" \
    "  -h, --help          Show this help"
}

if [[ "${1:-}" == "deploy" || "${1:-}" == "rollback" ]]; then
  COMMAND="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      SSH_TARGET="${2:-}"
      shift 2
      ;;
    --domain)
      SITE_DOMAIN="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --keep)
      KEEP_RELEASES="${2:-}"
      shift 2
      ;;
    --docker-image)
      DOCKER_IMAGE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "${SSH_TARGET}" =~ ^([A-Za-z0-9._-]+@)?[A-Za-z0-9._:-]+$ ]]; then
  printf 'Invalid SSH target: %s\n' "${SSH_TARGET}" >&2
  exit 2
fi

if [[ ! "${SITE_DOMAIN}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] ||
   [[ "${SITE_DOMAIN}" != *.* ]]; then
  printf 'Invalid site domain: %s\n' "${SITE_DOMAIN}" >&2
  exit 2
fi

if [[ ! "${KEEP_RELEASES}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Invalid release retention count: %s\n' "${KEEP_RELEASES}" >&2
  exit 2
fi

if [[ -n "${DOCKER_IMAGE}" ]] &&
   [[ ! "${DOCKER_IMAGE}" =~ ^[A-Za-z0-9._/@:+-]+$ ]]; then
  printf 'Invalid Docker image reference: %s\n' "${DOCKER_IMAGE}" >&2
  exit 2
fi

for command_name in ssh rsync curl sed python3; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "${command_name}" >&2
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

run_ssh() {
  ssh "${SSH_OPTIONS[@]}" "${SSH_TARGET}" "$@"
}

install_monitor() {
  local remote_dir
  remote_dir="/tmp/ournotes-monitor-$$"
  if ! run_ssh "mkdir -p '${remote_dir}/deploy' '${remote_dir}/tools'" ||
     ! rsync -az -e "ssh ${SSH_OPTIONS[*]}" "${DEPLOY_DIR}/monitor/" "${SSH_TARGET}:${remote_dir}/deploy/monitor/" ||
     ! rsync -az -e "ssh ${SSH_OPTIONS[*]}" "${REPO_ROOT}/tools/monitor/" "${SSH_TARGET}:${remote_dir}/tools/monitor/" ||
     ! run_ssh "chmod +x '${remote_dir}/tools/monitor/install.sh' && '${remote_dir}/tools/monitor/install.sh'"; then
    run_ssh "rm -rf '${remote_dir}'" || true
    return 1
  fi
  run_ssh "rm -rf '${remote_dir}'"
}

record_deployment_event() {
  local result="$1" failed_phase="${2:-}" reason_code="${3:-}" event_json phases_json
  printf -v phases_json '{"totalBuildSeconds":%s,"testsSeconds":%s,"resourceGenerationSeconds":%s,"matrixBuildSeconds":%s,"browserAndBuildBudgetSeconds":%s,"artifactManifestSeconds":%s,"diskCheckSeconds":%s,"artifactDiffSeconds":%s,"transferSeconds":%s,"activateAndVerifySeconds":%s,"healthCheckSeconds":%s}' \
    "${BUILD_SECONDS}" "${TEST_SECONDS}" "${RESOURCE_SECONDS}" "${MATRIX_SECONDS}" \
    "${BUDGET_SECONDS}" "${MANIFEST_SECONDS}" "${DISK_CHECK_SECONDS}" \
    "${ARTIFACT_DIFF_SECONDS}" "${TRANSFER_SECONDS}" "${ACTIVATE_SECONDS}" "${HEALTH_SECONDS}"
  if ! event_json="$(python3 "${REPO_ROOT}/tools/deployment_event.py" \
    --output "${DEPLOYMENT_EVENT_LOG}" --attempt-id "${ATTEMPT_ID}" \
    --command "${COMMAND}" --result "${result}" --release-id "${release_id}" \
    --git-commit "${git_commit}" --started-at "${ATTEMPT_STARTED_AT}" \
    --finished-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --failed-phase "${failed_phase}" --reason-code "${reason_code}" \
    --phases-json "${phases_json}" \
    --disk-json "{\"availableKiB\":${DISK_AVAILABLE_KB}}" \
    --rsync-json "{\"transferredFiles\":${RSYNC_TRANSFERRED_FILES},\"matchedFiles\":${RSYNC_MATCHED_FILES}}")"; then
    printf 'Warning: failed to write local deployment event.\n' >&2
    return 0
  fi
  if [[ "${REMOTE_EVENTS_READY}" -eq 1 ]]; then
    printf '%s\n' "${event_json}" | run_ssh \
      "install -d -m 0755 /var/log/ournotes && cat >>/var/log/ournotes/deployments.jsonl" \
      >/dev/null 2>&1 || true
  fi
}

finalize_deployment_event() {
  local original_status="$?"
  if [[ "${EVENT_FINALIZED}" -ne 1 && "${original_status}" -ne 0 ]]; then
    record_deployment_event "failed" "${CURRENT_PHASE}" "${REASON_CODE}" || true
  fi
  exit "${original_status}"
}

ensure_remote_requirements() {
  run_ssh 'bash -s' <<'REMOTE'
set -euo pipefail

if ! command -v rsync >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y rsync
  elif command -v yum >/dev/null 2>&1; then
    yum install -y rsync
  else
    printf 'rsync is missing and no supported package manager was found.\n' >&2
    exit 1
  fi
fi

for command_name in nginx certbot curl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'Required server command is missing: %s\n' "${command_name}" >&2
    exit 1
  fi
done
REMOTE
}

rollback_remote() {
  record_deployment_event "rollback_started" "rollback" "" || true
  if run_ssh 'bash -s' -- "${REMOTE_ROOT}" "${SITE_DOMAIN}" <<'REMOTE'
set -euo pipefail

root="$1"
domain="$2"
cd "${root}"

if [[ ! -L previous || ! -d previous ]]; then
  printf 'No previous release is available for rollback.\n' >&2
  exit 1
fi

current_target=""
if [[ -L current ]]; then
  current_target="$(readlink current)"
fi
previous_target="$(readlink previous)"

ln -sfn "${previous_target}" current.next
mv -Tf current.next current

if [[ -n "${current_target}" ]]; then
  ln -sfn "${current_target}" previous.next
  mv -Tf previous.next previous
fi

for attempt in $(seq 1 20); do
  if curl -fsS --max-time 5 \
    --resolve "${domain}:443:127.0.0.1" "https://${domain}/" >/dev/null; then
    printf 'Rolled back to %s\n' "${previous_target}"
    exit 0
  fi
  sleep 1
done

printf 'Rollback target failed the local health check; restoring %s\n' \
  "${current_target}" >&2
if [[ -n "${current_target}" ]]; then
  ln -sfn "${current_target}" current.next
  mv -Tf current.next current
fi
exit 1
REMOTE
  then
    record_deployment_event "rollback_succeeded" "rollback" "" || true
    return 0
  fi
  record_deployment_event "rollback_failed" "rollback" "rollback_health_failed" || true
  return 1
}

configure_nginx() {
  local bootstrap_file final_file remote_suffix
  bootstrap_file="$(mktemp)"
  final_file="$(mktemp)"
  remote_suffix="ournotes-nginx-$$"

  sed "s/__SITE_DOMAIN__/${SITE_DOMAIN}/g" \
    "${DEPLOY_DIR}/nginx-bootstrap.conf.template" >"${bootstrap_file}"
  sed "s/__SITE_DOMAIN__/${SITE_DOMAIN}/g" \
    "${DEPLOY_DIR}/nginx.conf.template" >"${final_file}"

  if ! rsync -az \
    -e "ssh ${SSH_OPTIONS[*]}" \
    "${bootstrap_file}" \
    "${SSH_TARGET}:/tmp/${remote_suffix}-bootstrap.conf"; then
    rm -f "${bootstrap_file}" "${final_file}"
    return 1
  fi
  if ! rsync -az \
    -e "ssh ${SSH_OPTIONS[*]}" \
    "${final_file}" \
    "${SSH_TARGET}:/tmp/${remote_suffix}-final.conf"; then
    rm -f "${bootstrap_file}" "${final_file}"
    return 1
  fi
  rm -f "${bootstrap_file}" "${final_file}"

  run_ssh 'bash -s' -- \
    "${REMOTE_ROOT}" \
    "${SITE_DOMAIN}" \
    "/tmp/${remote_suffix}-bootstrap.conf" \
    "/tmp/${remote_suffix}-final.conf" <<'REMOTE'
set -euo pipefail

root="$1"
domain="$2"
bootstrap_file="$3"
final_file="$4"
active_file="/etc/nginx/conf.d/ournotes.conf"
backup_file=""

cleanup() {
  rm -f "${bootstrap_file}" "${final_file}"
  if [[ -n "${backup_file}" ]]; then
    rm -f "${backup_file}"
  fi
}

trap cleanup EXIT

restore_config() {
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    cp "${backup_file}" "${active_file}"
  else
    rm -f "${active_file}"
  fi
  nginx -t
  systemctl reload nginx
}

if [[ -f "${active_file}" ]]; then
  backup_file="$(mktemp)"
  cp "${active_file}" "${backup_file}"
fi

if [[ ! -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]]; then
  cp "${bootstrap_file}" "${active_file}"
  if ! nginx -t; then
    restore_config
    exit 1
  fi
  systemctl reload nginx

  if ! certbot certonly \
    --webroot \
    --webroot-path "${root}/current" \
    --domain "${domain}" \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email; then
    restore_config
    exit 1
  fi
fi

cp "${final_file}" "${active_file}"
if ! nginx -t; then
  restore_config
  exit 1
fi
systemctl reload nginx
REMOTE
}

if [[ "${COMMAND}" == "rollback" ]]; then
  DEPLOYMENT_EVENT_CONTEXT_READY=1
  trap finalize_deployment_event EXIT
  record_deployment_event "started" "" "" || true
  CURRENT_PHASE="rollback"
  ensure_remote_requirements
  REMOTE_EVENTS_READY=1
  rollback_remote
  record_deployment_event "success" "" "" || true
  EVENT_FINALIZED=1
  exit 0
fi

DEPLOYMENT_EVENT_CONTEXT_READY=1
trap finalize_deployment_event EXIT
record_deployment_event "started" "" "" || true

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  CURRENT_PHASE="build"
  for command_name in node npm git python3; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      printf 'Required build command is missing: %s\n' "${command_name}" >&2
      exit 1
    fi
  done

  if ! git -C "${REPO_ROOT}" diff --quiet -- . ||
     ! git -C "${REPO_ROOT}" diff --cached --quiet -- .; then
    printf 'Refusing to build a release from tracked uncommitted changes.\n' >&2
    exit 1
  fi
  untracked_build_inputs="$(
    git -C "${REPO_ROOT}" ls-files --others --exclude-standard -- \
      site tools deploy catalog config Dockerfile.worker requirements-worker.txt
  )"
  if [[ -n "${untracked_build_inputs}" ]]; then
    printf 'Refusing to build a release from untracked build inputs:\n%s\n' \
      "${untracked_build_inputs}" >&2
    exit 1
  fi

  node_version="$(node -p 'process.versions.node')"
  node_major="${node_version%%.*}"
  node_minor_patch="${node_version#*.}"
  node_minor="${node_minor_patch%%.*}"
  if (( node_major < 22 || (node_major == 22 && node_minor < 20) )); then
    printf 'Node.js 22.20.0 or newer is required; active version is %s.\n' \
      "${node_version}" >&2
    printf 'With nvm installed, run: nvm install && nvm use\n' >&2
    exit 1
  fi

  build_started_epoch="$(date +%s)"
  phase_started_epoch="$(date +%s)"
  (cd "${SITE_DIR}" && npm run catalog:preflight)
  RESOURCE_SECONDS=$(( $(date +%s) - phase_started_epoch ))
  phase_started_epoch="$(date +%s)"
  (cd "${SITE_DIR}" && npm test)
  TEST_SECONDS=$(( $(date +%s) - phase_started_epoch ))
  phase_started_epoch="$(date +%s)"
  BUILD_ROOT="${REPO_ROOT}/output/release-builds/deploy-${ATTEMPT_ID}"
  (cd "${SITE_DIR}" && npm run build -- --output "${BUILD_ROOT}")
  DIST_DIR="${BUILD_ROOT}/site"
  RELEASE_INDEX="${DIST_DIR}/global/zh-CN/data/release-index.json"
  MEDIA_INDEX="${DIST_DIR}/global/zh-CN/data/media-index.json"
  MATRIX_SECONDS=$(( $(date +%s) - phase_started_epoch ))
  phase_started_epoch="$(date +%s)"
  (cd "${REPO_ROOT}" && python3 tools/performance_budget.py "${DIST_DIR}" --output output/readiness/build-budget.json)
  BUDGET_SECONDS=$(( $(date +%s) - phase_started_epoch ))
  BUILD_SECONDS=$(( $(date +%s) - build_started_epoch ))
fi

if [[ ! -f "${DIST_DIR}/index.html" ]]; then
  printf 'Build output is missing: %s/index.html\n' "${DIST_DIR}" >&2
  exit 1
fi

manifest_started_epoch="$(date +%s)"
CURRENT_PHASE="manifest"
git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
git_commit_short="${git_commit:0:12}"
if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  release_id="$(date -u +%Y%m%dt%H%M%Sz)-${git_commit_short}-$$"
  build_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ -z "${DOCKER_IMAGE}" ]]; then
    DOCKER_IMAGE="local-worktree:${git_commit_short}"
  fi
  (
    cd "${REPO_ROOT}"
    python3 -m tools.site_artifact build \
      --artifact-root "${DIST_DIR}" \
      --release-index "${RELEASE_INDEX}" \
      --package-lock "${PACKAGE_LOCK}" \
      --media-index "${MEDIA_INDEX}" \
      --site-release-id "${release_id}" \
      --git-commit "${git_commit}" \
      --docker-image "${DOCKER_IMAGE}" \
      --built-at "${build_time}"
  )
fi

release_id="$(
  cd "${REPO_ROOT}"
  python3 -m tools.site_artifact verify \
    --artifact-root "${DIST_DIR}" \
    --expected-git-commit "${git_commit}" \
    --package-lock "${PACKAGE_LOCK}" \
    --release-index "${RELEASE_INDEX}" \
    --print-site-release-id
)"
MANIFEST_SECONDS=$(( $(date +%s) - manifest_started_epoch ))

ensure_remote_requirements
REMOTE_EVENTS_READY=1

CURRENT_PHASE="disk"
required_kb="$(du -sk "${DIST_DIR}" | awk '{print $1}')"
disk_check_started_epoch="$(date +%s)"
disk_check_output="$(run_ssh 'bash -s' -- "${REMOTE_ROOT}" "${release_id}" "${required_kb}" <<'REMOTE'
set -euo pipefail

root="$1"
release_id="$2"
required_kb="$3"
mkdir -p "${root}/releases"

available_kb="$(df -Pk "${root}" | awk 'NR == 2 {print $4}')"
printf 'AVAILABLE_KB=%s\n' "${available_kb}"
minimum_kb=$((required_kb * 2))
if (( available_kb < minimum_kb )); then
  printf 'Insufficient disk space: need at least %s KiB, have %s KiB.\n' \
    "${minimum_kb}" "${available_kb}" >&2
  exit 1
fi

release_dir="${root}/releases/${release_id}"
if [[ -e "${release_dir}" ]]; then
  printf 'Release already exists: %s\n' "${release_dir}" >&2
  exit 1
fi

mkdir "${release_dir}"
if [[ -L "${root}/current" && -d "${root}/current" ]]; then
  cp -al "${root}/current/." "${release_dir}/"
fi
REMOTE
)"
DISK_CHECK_SECONDS=$(( $(date +%s) - disk_check_started_epoch ))
DISK_AVAILABLE_KB="${disk_check_output##*AVAILABLE_KB=}"

transfer_started_epoch="$(date +%s)"
CURRENT_PHASE="transfer"
artifact_diff_started_epoch="$(date +%s)"
rsync_stats_file="$(mktemp)"
if ! LANG=C rsync -azH --delete --stats --exclude=.DS_Store --delete-excluded \
  -e "ssh ${SSH_OPTIONS[*]}" \
  "${DIST_DIR}/" \
  "${SSH_TARGET}:${REMOTE_ROOT}/releases/${release_id}/" >"${rsync_stats_file}"; then
  rm -f "${rsync_stats_file}"
  run_ssh "rm -rf '${REMOTE_ROOT}/releases/${release_id}'"
  exit 1
fi
cat "${rsync_stats_file}"
RSYNC_TRANSFERRED_FILES="$(awk -F: '/Number of regular files transferred/ {gsub(/[^0-9]/, "", $2); print $2}' "${rsync_stats_file}")"
RSYNC_TRANSFERRED_FILES="${RSYNC_TRANSFERRED_FILES:-0}"
local_file_count="$(
  find "${DIST_DIR}" -type f ! -name .DS_Store | wc -l | tr -d ' '
)"
RSYNC_MATCHED_FILES=$(( local_file_count - RSYNC_TRANSFERRED_FILES ))
rm -f "${rsync_stats_file}"
ARTIFACT_DIFF_SECONDS=$(( $(date +%s) - artifact_diff_started_epoch ))
TRANSFER_SECONDS=$(( $(date +%s) - transfer_started_epoch ))

activate_started_epoch="$(date +%s)"
CURRENT_PHASE="activate"
run_ssh 'bash -s' -- "${REMOTE_ROOT}" "${release_id}" <<'REMOTE'
set -euo pipefail

root="$1"
release_id="$2"
cd "${root}"

old_target=""
if [[ -L current && -d current ]]; then
  old_target="$(readlink current)"
fi

if [[ -n "${old_target}" ]]; then
  ln -sfn "${old_target}" previous.next
  mv -Tf previous.next previous
fi

ln -sfn "releases/${release_id}" current.next
mv -Tf current.next current
REMOTE

if ! configure_nginx; then
  printf 'Nginx or certificate configuration failed; attempting rollback.\n' >&2
  if run_ssh "test -L '${REMOTE_ROOT}/previous'"; then
    rollback_remote || true
  fi
  exit 1
fi

if ! install_monitor; then
  printf 'Traffic monitor installation failed; the site remains active.\n' >&2
fi

health_started_epoch="$(date +%s)"
CURRENT_PHASE="health"
remote_healthy=0
for attempt in $(seq 1 30); do
  if run_ssh "curl -fsS --max-time 5 --resolve '${SITE_DOMAIN}:443:127.0.0.1' 'https://${SITE_DOMAIN}/' >/dev/null"; then
    remote_healthy=1
    break
  fi
  sleep 1
done

if [[ "${remote_healthy}" -ne 1 ]]; then
  printf 'Server-local HTTPS health check failed; attempting rollback.\n' >&2
  rollback_remote || true
  exit 1
fi

public_healthy=0
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 10 "https://${SITE_DOMAIN}/" >/dev/null; then
    public_healthy=1
    break
  fi
  sleep 2
done

if [[ "${public_healthy}" -ne 1 ]]; then
  printf 'Public HTTPS health check failed for https://%s/.\n' "${SITE_DOMAIN}" >&2
  if run_ssh "test -L '${REMOTE_ROOT}/previous'"; then
    rollback_remote || true
  else
    printf 'This is the first release, so it remains active for diagnosis.\n' >&2
  fi
  exit 1
fi
# Publish the website's immutable data API after its media is reachable.
# Existing clients keep their previous validated snapshot if publication fails.
qq_data_candidate="$(mktemp -d)"
if python3 "${REPO_ROOT}/tools/qqbot_publish_data.py" \
    --generated "${DIST_DIR}/global/zh-CN/data" --public-root "${DIST_DIR}" \
    --existing-site "${DIST_DIR}" --output "${qq_data_candidate}/api" &&
   run_ssh "mkdir -p '${REMOTE_ROOT}/data-api'" &&
   rsync -az --exclude current.json -e "ssh ${SSH_OPTIONS[*]}" \
       "${qq_data_candidate}/api/" "${SSH_TARGET}:${REMOTE_ROOT}/data-api/" &&
   rsync -az -e "ssh ${SSH_OPTIONS[*]}" "${qq_data_candidate}/api/current.json" \
       "${SSH_TARGET}:${REMOTE_ROOT}/data-api/current.next.json" &&
   run_ssh "mv -f '${REMOTE_ROOT}/data-api/current.next.json' '${REMOTE_ROOT}/data-api/current.json'"; then
  printf 'Website data API updated; bot caches refresh on their next version check.\n'
else
  printf 'Website data API was not updated; clients retain the previous snapshot.\n' >&2
fi
rm -rf -- "${qq_data_candidate}"

HEALTH_SECONDS=$(( $(date +%s) - health_started_epoch ))
ACTIVATE_SECONDS=$(( $(date +%s) - activate_started_epoch ))

run_ssh 'bash -s' -- "${REMOTE_ROOT}" "${KEEP_RELEASES}" <<'REMOTE'
set -euo pipefail

root="$1"
keep="$2"
cd "${root}"
current_target="$(readlink current 2>/dev/null || true)"
previous_target="$(readlink previous 2>/dev/null || true)"

find releases -mindepth 1 -maxdepth 1 -type d -printf '%P\n' |
  sort -r |
  awk -v keep="${keep}" 'NR > keep' |
  while IFS= read -r release; do
    candidate="releases/${release}"
    if [[ "${candidate}" != "${current_target}" && "${candidate}" != "${previous_target}" ]]; then
      rm -rf -- "${candidate}"
    fi
  done
REMOTE

record_deployment_event "success" "" "" || true
EVENT_FINALIZED=1

printf 'Published %s to https://%s/\n' "${release_id}" "${SITE_DOMAIN}"
