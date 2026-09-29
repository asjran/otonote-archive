"""Fill missing gallery bundles from the pinned public catalog, preserving the snapshot."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from tools.gallery_sources import TABLES, asset_reference, resolve_texture
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.transport import HttpRequest, HttpTransport


def download(snapshot: Path, output: Path):
    report = json.loads((snapshot / 'report.json').read_text())
    catalog = snapshot / 'RemoteCatalog/catalog_main.bin'
    if report['status'] != 'verified_snapshot' or hashlib.sha256(catalog.read_bytes()).hexdigest() != report['catalogSha256']:
        raise ValueError('Unverified snapshot')
    root = report['observation']['cdnRoot']
    host = 'l14-prod-hk-patch-sirius.gamerfusiontech.com'
    if urlsplit(root).scheme != 'https' or urlsplit(root).hostname != host:
        raise ValueError('Unexpected public host')
    locations = CatalogAdapter().parse(catalog).locations
    required = {}
    missing = []
    for kind, table in TABLES.items():
        for row in json.loads((snapshot / f'master-json/{table}.json').read_text())['_allData']:
            ref = asset_reference(kind, row)
            match = resolve_texture(locations, ref)
            if match is None:
                missing.append({'kind': kind, 'id': row['_id'], 'asset': ref})
            else:
                required[match[1].primary_key] = match[1]
    output.mkdir(parents=True, exist_ok=True)
    transport = HttpTransport(allowed_hosts=(host,), connect_timeout_seconds=20, read_timeout_seconds=60, max_response_bytes=30_000_000)
    count = 0
    for name, location in required.items():
        if (snapshot / 'assets' / name).is_file():
            continue
        target = output / name
        receipt_path = target.with_suffix('.receipt.json')
        if target.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt['catalogSha256'] != report['catalogSha256'] or hashlib.sha256(target.read_bytes()).hexdigest() != receipt['sha256']:
                raise ValueError('Cached supplement mismatch')
            continue
        if not re.fullmatch(r'[a-z0-9_-]+\.bundle', name):
            raise ValueError('Invalid catalog bundle name')
        url = root + '/asset/Android/' + name
        stream = io.BytesIO()
        receipt = transport.download(HttpRequest('GET', url), stream)
        payload = stream.getvalue()
        if receipt.status != 200 or len(payload) != location.expected_size:
            raise ValueError(f'Unexpected download size/status: {name}')
        etag = receipt.headers.get('etag', '').strip('"')
        if re.fullmatch('[a-fA-F0-9]{32}', etag) and hashlib.md5(payload).hexdigest() != etag.lower():
            raise ValueError('ETag mismatch')
        target.write_bytes(payload)
        receipt_path.write_text(json.dumps({'sha256': hashlib.sha256(payload).hexdigest(), 'byteSize': len(payload), 'catalogSha256': report['catalogSha256'], 'url': url, 'etag': etag}))
        count += 1
        if count % 20 == 0:
            print(f'Downloaded {count} missing bundles', flush=True)
    print(json.dumps({'downloaded': count, 'missingCatalogReferences': missing}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    download(args.snapshot, args.output)
