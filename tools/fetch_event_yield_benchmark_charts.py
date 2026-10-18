#!/usr/bin/env python3
"""Rebuild a hash-pinned local benchmark chart map (public data only)."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest', type=Path, required=True)
parser.add_argument('--catalog', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
catalog_bytes = args.catalog.read_bytes()
if hashlib.sha256(catalog_bytes).hexdigest() != manifest['catalogSha256']:
    raise SystemExit('Catalog SHA256 mismatch')
if json.loads(catalog_bytes)['release']['id'] != manifest['sourceReleaseId']:
    raise SystemExit('Catalog source release mismatch')
if len(manifest['charts']) != manifest['count']:
    raise SystemExit('Manifest chart count mismatch')
args.output_dir.mkdir(parents=True, exist_ok=True)

def fetch(chart):
    if not re.fullmatch(r'music-chart-\d+', chart['id']):
        raise ValueError('Invalid chart id')
    if not chart['url'].startswith('https://ournotes.stonebg.cn/content/releases/'):
        raise ValueError('Unexpected public content origin')
    target = args.output_dir / (chart['id'] + '.json')
    valid = lambda b: len(b) == chart['bytes'] and hashlib.sha256(b).hexdigest() == chart['sha256']
    if target.exists() and valid(target.read_bytes()):
        return chart['id'], str(target.resolve())
    with urllib.request.urlopen(chart['url'], timeout=60) as response:
        content = response.read()
    if not valid(content):
        raise ValueError('Chart content mismatch: ' + chart['id'])
    payload = json.loads(content)
    if payload['id'] != chart['id']:
        raise ValueError('Chart identity mismatch: ' + chart['id'])
    temporary = target.with_suffix('.json.part')
    temporary.write_bytes(content)
    temporary.replace(target)
    return chart['id'], str(target.resolve())

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    chart_map = dict(pool.map(fetch, manifest['charts']))
map_path = args.output_dir / 'chart-map.json'
map_path.write_text(json.dumps(chart_map, indent=2) + '\n')
print(json.dumps({'charts': len(chart_map), 'chartMap': str(map_path.resolve())}))
