#!/usr/bin/env python3
"""Export the archived mission banners; validate each source against capture digests."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    CATALOG_SHA256, KEY_FIELD_USAGE, METADATA_SHA256, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter


def extract():
    capture_root = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    catalog_path = capture_root / 'RemoteCatalog/catalog_main.bin'
    if sha256(catalog_path) != CATALOG_SHA256 or sha256(metadata_path) != METADATA_SHA256:
        raise ValueError('Unexpected catalog or metadata digest')
    capture = json.loads((capture_root / 'capture.json').read_text())
    recorded = {r['path']: r for r in capture['files']}
    metadata = MetadataV39(metadata_path)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    names = ['limited_mission_banner_0001', 'limited_mission_banner_1000000001']
    locations = CatalogAdapter().parse(catalog_path).locations
    output = ROOT / 'site/public/system-banners'
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for name in names:
        matches = [loc for loc in locations if f'_{name}_' in loc.primary_key
                   and re.search(r'_[a-f0-9]{32}\.bundle$', loc.primary_key)]
        if len(matches) != 1:
            raise ValueError(f'{name}: expected one bundle')
        loc = matches[0]
        bundle_id = loc.primary_key[:-7].rsplit('_', 1)[-1]
        sources = list((capture_root / 'EncryptedBundles').glob(f'{bundle_id}_*.bundle'))
        if len(sources) != 1:
            raise ValueError(f'{name}: expected one captured source')
        source = sources[0]
        relative = source.relative_to(capture_root).as_posix()
        record = recorded[relative]
        if source.stat().st_size != loc.expected_size or sha256(source) != record['sha256']:
            raise ValueError(f'{name}: captured digest mismatch')
        environment = UnityPy.load(decrypt_header(source.read_bytes(), loc.primary_key, key, seed))
        textures = [obj for obj in environment.objects if obj.type.name == 'Texture2D' and obj.read().m_Name == name]
        if len(textures) != 1:
            raise ValueError(f'{name}: expected one texture')
        image = textures[0].read().image
        target = output / f'{name}.webp'
        image.save(target, format='WEBP', quality=92)
        report.append({'name': name, 'source': relative, 'sourceSha256': record['sha256'],
                       'file': target.name, 'sha256': sha256(target), 'width': image.width, 'height': image.height})
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    print(json.dumps(extract(), ensure_ascii=False, indent=2))
