#!/usr/bin/env bash
# Upload only a validated code release. Resource data stays on the server.
set -euo pipefail
cd "$(dirname "$0")/.."
source_dir=${1:?Usage: publish-web-client.sh output/web-client-VERSION [ssh-host]}
target_host=${2:-your-server}
[[ "$target_host" =~ ^[a-zA-Z0-9_.@-]+$ ]] || exit 2
python3 -m tools.code_publication --source "$source_dir" --verify-only
code_id=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["codeId"])' "$source_dir/code-release.json")
[[ "$code_id" =~ ^[a-f0-9]{24}$ ]] || exit 2
ssh "$target_host" "mkdir -p /srv/ournotes-code/incoming/$code_id"
rsync -r --checksum --exclude=.DS_Store "$source_dir/" "$target_host:/srv/ournotes-code/incoming/$code_id/"
ssh "$target_host" "docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 0.5 --memory 128m --env PYTHONDONTWRITEBYTECODE=1 --mount type=bind,source=/srv/ournotes-updater/app/tools,target=/srv/ournotes-updater/app/tools,readonly --mount type=bind,source=/srv/ournotes-code,target=/srv/ournotes-code ournotes-global-update:20260928-v1 python3 -m tools.code_publication --source /srv/ournotes-code/incoming/$code_id --root /srv/ournotes-code"
