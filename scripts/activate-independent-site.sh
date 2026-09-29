#!/usr/bin/env bash
# Run after content and code publication. Keep the old static site as rollback.
set -euo pipefail
[[ ${EUID} == 0 ]] || { echo 'Run on the server as root.' >&2; exit 1; }
app=/srv/ournotes-updater/app
domain=otonote.example.com
site_config=/etc/nginx/conf.d/ournotes.conf
snippet=/etc/nginx/ournotes-independent/locations.conf
test -f /srv/ournotes-updater/content/current.json
test -L /srv/ournotes-code/current
python3 - <<'PY'
import json
with open('/srv/ournotes-updater/app/output/global-update-workflow/latest-run.json') as f: report=json.load(f)
with open('/srv/ournotes-updater/content/current.json') as f: pointer=json.load(f)
assert report['status']=='passed', 'Content update has not succeeded'
assert report['result']['publication']['pointer']==pointer, 'Content pointer does not match the successful update'
assert not any(s['name']=='build-site' for s in report['steps']), 'Expected a content-only update'
PY
backup=/etc/ournotes/independent-backups/$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$backup"
cp -p "$site_config" "$backup/ournotes.conf"
if [[ -f "$snippet" ]]; then cp -p "$snippet" "$backup/locations.conf"; fi
restore() {
  cp -p "$backup/ournotes.conf" "$site_config"
  if [[ -f "$backup/locations.conf" ]]; then cp -p "$backup/locations.conf" "$snippet"; else rm -f "$snippet"; fi
  nginx -t && systemctl reload nginx
  echo "Activation failed; restored $backup" >&2
}
trap restore ERR
install -d -m 0755 /etc/nginx/ournotes-independent
install -m 0644 "$app/deploy/independent-content.locations.conf" "$snippet"
python3 - "$site_config" <<'PY'
import sys,os
path=sys.argv[1]
with open(path) as stream: source=stream.read()
include='    include /etc/nginx/ournotes-independent/*.conf;'
anchor='    location ~ ^/(?:_astro|(?:jp|global)/(?:zh-CN|zh-TW|ja|en)/_astro)/ {'
if include not in source:
    if source.count(anchor)!=1: raise SystemExit('Expected static route anchor missing; configuration preserved')
    with open(path+'.next','w') as stream: stream.write(source.replace(anchor,include+'\n\n'+anchor))
    os.chmod(path+'.next',0o644);os.replace(path+'.next',path)
PY
nginx -t
systemctl reload nginx
probe() {
  # nginx reload returns before replacement workers have taken the listeners.
  for attempt in {1..10}; do
    if curl --fail --silent --show-error --max-time 10 --noproxy '*' --resolve "$domain:443:127.0.0.1" "https://$domain$1" > "$2"; then return 0; fi
    sleep 1
  done
  return 1
}
probe /content/current.json "$backup/content-after.json"
probe /global/zh-CN/ "$backup/frontend-after.html"
python3 - "$backup" <<'PY'
import json,sys
with open('/srv/ournotes-code/current/code-release.json') as f: code=json.load(f)
with open(sys.argv[1]+'/content-after.json') as f: content=json.load(f)
with open(sys.argv[1]+'/frontend-after.html') as f: html=f.read()
assert content['schemaVersion']==code['contentSchemaVersion']==1
assert '/app/releases/'+code['codeId']+'/' in html
PY
trap - ERR
echo "Independent site enabled. Rollback backup: $backup"
echo 'After browser acceptance: systemctl enable --now global-update.timer'
