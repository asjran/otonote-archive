#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MONITOR_PORT="${OURNOTES_MONITOR_PORT:-19090}"
if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run this installer as root.\n' >&2
  exit 1
fi
install -d -m 0755 /usr/local/lib/ournotes-monitor /etc/ournotes-monitor /var/lib/ournotes-monitor/report
install -m 0755 "${REPO_ROOT}/tools/monitor/collect.py" /usr/local/lib/ournotes-monitor/collect.py
install -m 0755 "${REPO_ROOT}/tools/monitor/render.py" /usr/local/lib/ournotes-monitor/render.py
install -m 0755 "${REPO_ROOT}/tools/monitor/recover.py" /usr/local/lib/ournotes-monitor/recover.py
if [[ ! -f /etc/ournotes-monitor/monitor.toml ]]; then
  install -m 0600 "${REPO_ROOT}/deploy/monitor/monitor.example.toml" /etc/ournotes-monitor/monitor.toml
  monitor_salt="$(openssl rand -hex 32)"
  sed -i "s/replace-with-a-random-server-local-secret/${monitor_salt}/" /etc/ournotes-monitor/monitor.toml
fi
install -m 0644 "${REPO_ROOT}/deploy/monitor/ournotes-monitor.service" /etc/systemd/system/ournotes-monitor.service
install -m 0644 "${REPO_ROOT}/deploy/monitor/ournotes-monitor.timer" /etc/systemd/system/ournotes-monitor.timer
install -m 0644 "${REPO_ROOT}/deploy/monitor/ournotes-monitor.logrotate" /etc/logrotate.d/ournotes-monitor
monitor_nginx_conf=/etc/nginx/conf.d/ournotes-monitor.conf
monitor_nginx_backup="${monitor_nginx_conf}.install-backup"
if [[ -f "${monitor_nginx_conf}" ]]; then
  cp -p "${monitor_nginx_conf}" "${monitor_nginx_backup}"
else
  rm -f "${monitor_nginx_backup}"
fi
monitor_nginx_temp="$(mktemp /etc/nginx/conf.d/ournotes-monitor.conf.XXXXXX)"
sed "s/__MONITOR_PORT__/${MONITOR_PORT}/g" "${REPO_ROOT}/deploy/monitor/nginx-loopback.conf.template" >"${monitor_nginx_temp}"
mv "${monitor_nginx_temp}" "${monitor_nginx_conf}"
if ! nginx -t; then
  if [[ -f "${monitor_nginx_backup}" ]]; then
    mv "${monitor_nginx_backup}" "${monitor_nginx_conf}"
  else
    rm -f "${monitor_nginx_conf}"
  fi
  nginx -t || true
  printf 'Monitoring Nginx configuration failed validation and was rolled back.\n' >&2
  exit 1
fi
rm -f "${monitor_nginx_backup}"
systemctl reload nginx
systemctl daemon-reload
systemctl enable --now ournotes-monitor.timer
systemctl start ournotes-monitor.service
