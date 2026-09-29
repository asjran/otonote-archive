"""Export one verified Global game skin for the browser chart player.

Run: python3 -B tools/prepare_auto_stage.py
Only decoded textures are published; source bundles and key material stay local.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    CatalogAdapter, MetadataV39, UnityPy, CATALOG_SHA256, METADATA_SHA256,
    KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE, decrypt_header, field_bytes, sha256,
)

PREFIXES = (
    'live-note_assets_everythinglive-note-skin001_',
    'live_assets_live_lane_skin001_',
    'live_assets_live_uispriteassets_atlassources_livecomboatlas_sp_combo_perfect_',
    'live_assets_live_uispriteassets_atlassources_judgementatlas_judgment_perfect_',
    'effect_assets_effect_live_noteeffect_common_texture_ef_tap_line_',
    'effect_assets_effect_live_noteeffect_common_texture_ef_tap_pillar_',
    'effect_assets_effect_live_noteeffect_common_texture_ef_tap_particle_star_',
    'band_assets_band_0_live_stage_live_stage_bg_sprite_',
    'live_assets_live_uispriteassets_atlas_livecomboatlas_',
    'live_assets_live_uispriteassets_atlas_judgementatlas_',
)


def main():
    capture_root = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    catalog_path = capture_root / 'RemoteCatalog/catalog_main.bin'
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    if sha256(catalog_path) != CATALOG_SHA256 or sha256(metadata_path) != METADATA_SHA256:
        raise ValueError('Unexpected Global source catalog or metadata')
    records = {x['path']: x for x in json.loads((capture_root / 'capture.json').read_text())['files']}
    locations = CatalogAdapter().parse(catalog_path).locations
    metadata = MetadataV39(metadata_path)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    destination = ROOT / 'site/public/auto-stage/skin001'
    destination.mkdir(parents=True, exist_ok=True)
    images, sources = {}, []
    selected = [loc for loc in locations if loc.primary_key.startswith(PREFIXES)
                and loc.provider_id.endswith('.AssetBundleCryptProvider')]
    bundles = []
    for loc in selected:
        name = loc.primary_key
        # Exclude similarly named variants: only the exact resource plus its hash.
        matched = next(prefix for prefix in PREFIXES if name.startswith(prefix))
        suffix = name[len(matched):]
        if matched == 'live_assets_live_lane_skin001_' and not re.fullmatch(r'(lane_base|lane_tap_area|out_side_line)_[a-f0-9]{32}\.bundle', suffix):
            continue
        if 'sp_combo_perfect_' in matched:
            if not re.fullmatch(r'(?:[0-9]_)?[a-f0-9]{32}\.bundle', suffix):
                continue
        elif matched != 'live_assets_live_lane_skin001_' and not re.fullmatch(r'[a-f0-9]{32}\.bundle', suffix):
            continue
        bundle_hash = name[:-7].rsplit('_', 1)[-1]
        files = list((capture_root / 'EncryptedBundles').glob(bundle_hash + '_*.bundle'))
        if len(files) != 1:
            raise ValueError(f'Missing local resource: {name}')
        source = files[0]
        record = records.get(source.relative_to(capture_root).as_posix())
        if not record or sha256(source) != record['sha256'] or source.stat().st_size != loc.expected_size:
            raise ValueError(f'Bundle validation failed: {name}')
        bundles.append((name, record, decrypt_header(source.read_bytes(), name, key, seed)))
        sources.append({'bundle': name, 'sha256': record['sha256']})
    return export_bundles(bundles, sources, destination, ROOT / 'site/src/data/auto-stage-skin.json', CATALOG_SHA256)


def export_bundles(bundles, sources, destination, catalog_output, catalog_sha256):
    images = {}
    atlases = [clear for name, _, clear in bundles if '_uispriteassets_atlas_' in name]
    names = {f'notes_{family}_side_{part}' for family in ('tap', 'flick', 'flick_left', 'flick_right', 'slide', 'slide_end', 'slide_connection', 'trace') for part in ('L', '0', 'R')}
    names.update({'tap_decoration', 'slide_connection_icon'})
    names.update(f'notes_flick_arrow_{direction}_{index:02d}' for direction in ('left', 'right') for index in range(1, 9))
    names.update(f'notes_flick_arrow_upper_{size}' for size in ('S', 'M', 'L', 'LL'))
    names.update({'notes_flick_arrow_upper_M', 'notes_flick_arrow_left_04', 'notes_flick_arrow_right_04', 'flick_decoration', 'flick_left_decoration', 'flick_right_decoration', 'slide_decoration', 'lane_base', 'lane_tap_area', 'out_side_line', 'ef_tap_line', 'ef_tap_pillar', 'ef_tap_particle_star', 'live_stage_bg_sprite', 'judgment_perfect', 'SP_combo_perfect'})
    names.update(f'SP_combo_perfect_{i}' for i in range(10))
    for name, record, clear in bundles:
        if '_uispriteassets_atlas_' in name:
            continue
        env = UnityPy.load(clear, *atlases)
        sprite_names = {obj.read().m_Name for obj in env.objects if obj.type.name == 'Sprite'}
        for obj in env.objects:
            if obj.type.name not in ('Sprite', 'Texture2D'):
                continue
            data = obj.read()
            label = data.m_Name
            if obj.type.name == 'Texture2D' and label in sprite_names:
                continue
            if label not in names:
                continue
            texture = data.image.convert('RGBA')
            slug = re.sub('[^a-zA-Z0-9_-]', '-', label)
            # Hash source bytes for immutable, cache-safe URLs.
            filename = f'{slug}-{record["sha256"][:10]}.webp'
            target = destination / filename
            texture.save(target, format='WEBP', lossless=True)
            entry = {'url': '/auto-stage/skin001/' + filename, 'width': texture.width,
                     'height': texture.height, 'bytes': target.stat().st_size,
                     'sha256': sha256(target), 'bundle': name, 'pathId': obj.path_id}
            if label in images and images[label]['sha256'] != entry['sha256']:
                raise ValueError(f'Ambiguous texture: {label}')
            images[label] = entry
    missing = names - images.keys()
    if missing:
        raise ValueError(f'Missing textures: {sorted(missing)}')
    payload = {'schemaVersion': 1, 'id': 'global-skin001', 'catalogSha256': catalog_sha256,
               'images': images, 'sources': sources}
    catalog_output.parent.mkdir(parents=True, exist_ok=True)
    catalog_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'textures': len(images), 'bytes': sum(x['bytes'] for x in images.values()),
                      'names': list(images)}, ensure_ascii=False, indent=2))

    return payload

if __name__ == '__main__':
    main()
