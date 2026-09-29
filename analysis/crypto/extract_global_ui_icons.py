#!/usr/bin/env python3
"""Extract taxonomy sprites, band logos and skill icons from verified Global inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    CATALOG_SHA256, METADATA_SHA256, KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter

TAXONOMY_NAMES = {
    *(f'sp_icon_live_music_type_{code}' for code in (1, 3, 4, 5, 99)),
    'sp_icon_member_card_type_2',
    *(f'RarityIconCenter_{label}' for label in ('R', 'SR', 'SSR', 'BD', 'EX')),
    'MemberExpIcon', 'SnapExpIcon', 'SpecialTraining', 'Icon_Awakened', 'awakening_base',
}

def extract(output: Path) -> dict:
    if output.exists():
        raise ValueError('output already exists')
    capture = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    apk_root = ROOT / 'input/global/apks/2026-09-22-v1.0.1-25'
    apk = apk_root / 'base.apk'
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    catalog = capture / 'RemoteCatalog/catalog_main.bin'
    apk_record = next(row for row in json.loads((apk_root / 'capture.json').read_text())['files'] if row['name'] == 'base.apk')
    if sha256(apk) != apk_record['sha256'] or apk.stat().st_size != apk_record['size_bytes']:
        raise ValueError('APK digest mismatch')
    if sha256(metadata_path) != METADATA_SHA256 or sha256(catalog) != CATALOG_SHA256:
        raise ValueError('catalog/metadata digest mismatch')
    recorded = {row['path']: row for row in json.loads((capture / 'capture.json').read_text())['files']}
    metadata = MetadataV39(metadata_path)
    key, seed = field_bytes(metadata, KEY_FIELD_USAGE, 16), field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        temp = Path(temporary)
        assets, sources = [], []
        def save(obj, bundle, container, filename):
            data = obj.read()
            image = data.image
            target = temp / 'png' / filename
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                raise ValueError(f'duplicate image: {filename}')
            image.save(target)
            assets.append(dict(type=obj.type.name, name=data.m_Name, bundle=bundle, path_id=obj.path_id,
                               container_path=container, exported_file=f'png/{filename}',
                               width=image.width, height=image.height, sha256=sha256(target)))
        with zipfile.ZipFile(apk) as archive:
            atlas_path = next(n for n in archive.namelist() if 'ui_assets_embui_atlas_fixuispriteatlas_' in n)
            localized_path = 'assets/aa/Android/localization-assets-japanese(ja)_assets_all.bundle'
            environment = UnityPy.Environment()
            for name in (atlas_path, localized_path):
                raw = archive.read(name)
                environment.load_file(decrypt_header(raw, Path(name).name, key, seed), name=Path(name).name)
                sources.append(dict(source=name, sha256=hashlib.sha256(raw).hexdigest(), apkSha256=apk_record['sha256']))
            found = set()
            for obj in environment.objects:
                if obj.type.name == 'Sprite' and obj.read().m_Name in TAXONOMY_NAMES:
                    name = obj.read().m_Name
                    if name in found:
                        raise ValueError(f'duplicate sprite: {name}')
                    found.add(name)
                    bundle = Path(localized_path if name == 'Icon_Awakened' else atlas_path).name
                    save(obj, bundle, '', f'ui-{name.lower()}.png')
            if found != TAXONOMY_NAMES:
                raise ValueError(f'missing taxonomy sprites: {TAXONOMY_NAMES - found}')
        locations = CatalogAdapter().parse(catalog).locations
        for loc in locations:
            name = loc.primary_key
            if not (name.startswith('character_assets_character_skill_') or
                    (name.startswith('band_assets_band_') and '_band_logo' in name)):
                continue
            if not loc.provider_id.endswith('.AssetBundleCryptProvider'):
                continue
            bundle_id = name[:-7].rsplit('_', 1)[-1]
            matches = list((capture / 'EncryptedBundles').glob(f'{bundle_id}_*.bundle'))
            if len(matches) != 1:
                raise ValueError(f'missing unique cached bundle: {name}')
            source = matches[0]
            relative = source.relative_to(capture).as_posix()
            record = recorded[relative]
            if sha256(source) != record['sha256'] or source.stat().st_size != loc.expected_size:
                raise ValueError(f'bundle digest mismatch: {name}')
            env = UnityPy.load(decrypt_header(source.read_bytes(), name, key, seed))
            textures = [(path, obj) for path, obj in env.container.items() if obj.type.name == 'Texture2D']
            if len(textures) != 1:
                raise ValueError(f'expected one icon Texture2D: {name}')
            path, obj = textures[0]
            save(obj, name, path, 'ui-' + path.replace('/', '-').lower())
            sources.append(dict(source=relative, bundle=name, encryptedSha256=record['sha256']))
        if len(assets) != 51:
            raise ValueError(f'expected 16 taxonomy + 10 band + 25 skill images, got {len(assets)}')
        (temp / 'manifest.json').write_text(json.dumps({'assets': assets}, ensure_ascii=False, indent=2) + '\n')
        report = dict(catalogSha256=CATALOG_SHA256, metadataSha256=METADATA_SHA256,
                      apkSha256=apk_record['sha256'], extractedImageCount=len(assets), sources=sources,
                      manifestSha256=sha256(temp / 'manifest.json'))
        (temp / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        temp.rename(output)
    return {k: report[k] for k in ('extractedImageCount', 'manifestSha256')}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(extract(parser.parse_args().output), indent=2))
