#!/usr/bin/env bash
# Disable only this updater; keep site releases and private inputs intact.
set -euo pipefail
if [[ "${EUID}" != 0 ]]; then echo 'Run as root on the deployment server.' >&2; exit 1; fi
systemctl disable --now global-update.timer
systemctl stop global-update.service
if [[ -f /etc/ournotes/global-update.permissions.before ]]; then
  while read -r path mode owner group; do
    case "$path" in /srv/ournotes|/srv/ournotes/releases) ;; *) echo 'Unexpected permission record' >&2; exit 1;; esac
    chown "$owner:$group" "$path"
    chmod "$mode" "$path"
  done < /etc/ournotes/global-update.permissions.before
fi
# No release deletion or implicit rollback of the currently published website.
