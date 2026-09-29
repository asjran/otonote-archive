#!/usr/bin/env python3
"""Export TGW art and the game's serialized band-rank labels from verified inputs."""
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    CATALOG_SHA256, METADATA_SHA256, KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from UnityPy.classes import PPtr
from tools.resource_pipeline.catalog_adapter import CatalogAdapter


def extract():
    capture = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    apk_root = ROOT / 'input/global/apks/2026-09-22-v1.0.1-25'
    apk = apk_root / 'base.apk'
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    catalog = capture / 'RemoteCatalog/catalog_main.bin'
    apk_record = next(r for r in json.loads((apk_root / 'capture.json').read_text())['files'] if r['name'] == 'base.apk')
    if sha256(apk) != apk_record['sha256'] or sha256(metadata_path) != METADATA_SHA256 or sha256(catalog) != CATALOG_SHA256:
        raise ValueError('Unexpected APK, metadata or catalog digest')
    recorded = {r['path']: r for r in json.loads((capture / 'capture.json').read_text())['files']}
    metadata = MetadataV39(metadata_path)
    key, seed = field_bytes(metadata, KEY_FIELD_USAGE, 16), field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    output = ROOT / 'site/public/growth'
    output.mkdir(parents=True, exist_ok=True)
    images, ranks = [], []

    def save(image, name, source, source_hash):
        target = output / f'{name}.webp'
        image.save(target, format='WEBP', quality=92)
        images.append(dict(name=name, file=target.name, source=source, sourceSha256=source_hash,
                           sha256=sha256(target), width=image.width, height=image.height))
        return target.name

    for loc in CatalogAdapter().parse(catalog).locations:
        if not loc.primary_key.startswith('image_assets_image_tgw_') or not loc.primary_key.endswith('.bundle'):
            continue
        bundle_id = loc.primary_key[:-7].rsplit('_', 1)[-1]
        sources = list((capture / 'EncryptedBundles').glob(f'{bundle_id}_*.bundle'))
        if len(sources) != 1:
            raise ValueError(f'Expected one source: {loc.primary_key}')
        source = sources[0]
        relative = source.relative_to(capture).as_posix()
        if source.stat().st_size != loc.expected_size or sha256(source) != recorded[relative]['sha256']:
            raise ValueError(f'Captured digest mismatch: {relative}')
        env = UnityPy.load(decrypt_header(source.read_bytes(), loc.primary_key, key, seed))
        for obj in env.objects:
            if obj.type.name == 'Texture2D':
                data = obj.read()
                save(data.image, data.m_Name, relative, recorded[relative]['sha256'])

    env = UnityPy.Environment()
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if '_fixparts_band_uibandrankicon_' in name or '_texture_bandrank_' in name:
                env.load_file(decrypt_header(archive.read(name), Path(name).name, key, seed), name=Path(name).name)
        for obj in env.objects:
            if obj.type.name != 'MonoBehaviour':
                continue
            tree = obj.read_typetree()
            if '_type' not in tree:
                continue
            for entry in tree['_type']:
                pointer = PPtr(**entry['sprite'], assetsfile=obj.assets_file)
                sprite = pointer.read()
                label = sprite.m_Name.removeprefix('ImgScorerank_')
                if not re.fullmatch(r'(D|C|B|A|S|SS)[1-4]', label):
                    raise ValueError(f'Unexpected band rank: {label}')
                filename = save(sprite.image, f'band-rank-{label.lower()}',
                                'base.apk:UIBandRankIcon._type', apk_record['sha256'])
                ranks.append(dict(rank=entry['bandRank'], label=label, image=filename))
    ranks.sort(key=lambda r: r['rank'])
    if [r['rank'] for r in ranks] != list(range(1, 25)):
        raise ValueError('Incomplete band-rank mapping')
    report = dict(catalogSha256=CATALOG_SHA256, bandRanks=ranks, images=images)
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return dict(images=len(images), bandRanks=ranks)


if __name__ == '__main__':
    print(json.dumps(extract(), ensure_ascii=False, indent=2))
