#!/usr/bin/env bash
# Run on the server after uploading and verifying the complete private app tree.
set -euo pipefail
if [[ "${EUID}" != 0 ]]; then echo 'Run as root on the deployment server.' >&2; exit 1; fi
app=/srv/ournotes-updater/app
image=${OURNOTES_UPDATE_IMAGE:-ournotes-global-update:20260928-v1}
test -f "$app/config/global-update.server.json"
test -L /srv/ournotes/current
docker image inspect "$image" >/dev/null
id ournotes-update >/dev/null 2>&1 || useradd --system --home-dir /srv/ournotes-updater --shell /sbin/nologin ournotes-update
install -d -m 0750 /etc/ournotes
install -d -m 0755 /srv/ournotes-updater
mkdir -p "$app/output/tmp"
chown -R ournotes-update:ournotes-update /srv/ournotes-updater/app
chmod 0700 /srv/ournotes-updater/app
install -d -m 0755 -o ournotes-update -g ournotes-update /srv/ournotes-updater/content
chown -R ournotes-update:ournotes-update /srv/ournotes-updater/content
cat > /etc/ournotes/global-update.env <<ENV
OURNOTES_UID=$(id -u ournotes-update)
OURNOTES_GID=$(id -g ournotes-update)
OURNOTES_UPDATE_IMAGE=$image
ENV
chmod 0640 /etc/ournotes/global-update.env
install -m 0644 "$app/deploy/global-update.service" /etc/systemd/system/global-update.service
install -m 0644 "$app/deploy/global-update.timer" /etc/systemd/system/global-update.timer
systemctl daemon-reload
# The first run and verification are explicit; timer activation follows success.
echo 'Installed. Run: systemctl start global-update.service'
