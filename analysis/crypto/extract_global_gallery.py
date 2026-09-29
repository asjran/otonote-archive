#!/usr/bin/env python3
"""Export Master-bound comics, stamps and profile decorations from a verified local remote snapshot."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    KEY_FIELD_USAGE, METADATA_SHA256, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter

from tools.gallery_sources import TABLES, asset_reference, resolve_texture


def extract(snapshot: Path, master: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError('Choose a new output directory')
    report = json.loads((snapshot / 'report.json').read_text())
    catalog = snapshot / 'RemoteCatalog/catalog_main.bin'
    if report['status'] != 'verified_snapshot' or sha256(catalog) != report['catalogSha256']:
        raise ValueError('Unverified snapshot/catalog')
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    if sha256(metadata_path) != METADATA_SHA256:
        raise ValueError('Unexpected decoder metadata')
    metadata = MetadataV39(metadata_path)
    key, seed = field_bytes(metadata, KEY_FIELD_USAGE, 16), field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    tables = {}
    for name in TABLES.values():
        if sha256(master / f'{name}.json') != sha256(snapshot / f'master-json/{name}.json'):
            raise ValueError(f'{name}: snapshot differs from selected site Master')
        tables[name] = json.loads((master / f'{name}.json').read_text())['_allData']
    locations = CatalogAdapter().parse(catalog).locations
    recorded = {Path(row['path']).name: row for row in report['files']}
    assets = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gallery-', dir=output.parent) as folder:
        temp = Path(folder)
        for kind, table in TABLES.items():
            rows = tables[table]
            for row in rows:
                asset = asset_reference(kind, row)
                match = resolve_texture(locations, asset)
                if match is None:
                    assets.append({'kind': kind, 'id': row['_id'], 'asset': asset,
                                   'status': 'missing', 'reason': 'not_in_resource_catalog'})
                    continue
                texture_location, loc = match
                source = snapshot / 'assets' / loc.primary_key
                receipt = recorded.get(source.name)
                if not source.exists():
                    source = ROOT / 'output/verification/gallery-supplement-104' / loc.primary_key
                    receipt = json.loads(source.with_suffix('.receipt.json').read_text())
                    if receipt['catalogSha256'] != report['catalogSha256']:
                        raise ValueError('Supplement catalog mismatch')
                if not receipt or sha256(source) != receipt['sha256'] or source.stat().st_size != loc.expected_size:
                    raise ValueError(f'Bundle validation failed: {asset}')
                payload = source.read_bytes()
                env = UnityPy.load(payload if payload.startswith(b'UnityFS\0') else decrypt_header(payload, source.name, key, seed))
                container = texture_location.internal_id
                textures = [obj for path, obj in env.container.items() if path == container and obj.type.name == 'Texture2D']
                if len(textures) != 1:
                    raise ValueError(f'Expected one texture: {container}')
                image = textures[0].read().image.convert('RGBA')
                name = f"{kind}-{row['_id']}"
                image.save(temp / f'{name}.png')
                thumb = image.copy()
                thumb.thumbnail((720, 720) if kind == 'comics' else (320, 320))
                thumb.save(temp / f'{name}.webp', format='WEBP', quality=90)
                assets.append({'kind': kind, 'id': row['_id'], 'asset': asset,
                    'image': f'{name}.png', 'thumbnail': f'{name}.webp',
                    'width': image.width, 'height': image.height,
                    'status': 'available', 'sha256': sha256(temp / f'{name}.png'), 'thumbnailSha256': sha256(temp / f'{name}.webp'),
                    'bundle': source.name, 'bundleSha256': receipt['sha256'], 'container': container})
        manifest = {'schemaVersion': 2, 'resourceVersion': report['observation']['resourceVersion'],
            'catalogSha256': report['catalogSha256'],
            'masterSha256': {name: sha256(master / f'{name}.json') for name in TABLES.values()}, 'assets': assets}
        (temp / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        temp.rename(output)
    return {kind: len(tables[table]) for kind, table in TABLES.items()}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.snapshot, args.master, args.output)))
