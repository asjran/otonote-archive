"""Package every current Global catalog model, with auditable byte manifests.

Run: python3 -B tools/prepare_live2d.py [--characters 1 2]
Original bundles and bound release inputs are read only.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import re
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import (
    CatalogAdapter, MetadataV39, UnityPy, CATALOG_SHA256, METADATA_SHA256,
    KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE, decrypt_header, field_bytes, sha256,
)
from tools.live2d_conversion import build_model3, build_expression3, build_physics3, convert_motion_library
from tools.resource_pipeline.golden import _master_aggregate
from tools.live2d_assets import verify_live2d_assets
from tools.live2d_discovery import discover_models, story_character_labels


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')


def parameter_binding(obj):
    game = obj.read().m_GameObject.read()
    parameter_id = game.m_Name
    transform = game.m_Transform.read()
    parts = [parameter_id]
    while transform.m_Father.path_id:
        transform = transform.m_Father.read()
        parts.append(transform.m_GameObject.read().m_Name)
    path = '/'.join(reversed(parts))
    return zlib.crc32('/'.join(path.split('/')[1:]).encode()) & 0xffffffff, parameter_id


def export_model(env, destination, name):
    destination.mkdir(parents=True)
    textures, expressions, clips, bindings = [], [], {}, {}
    moc = physics = None
    defaults = {}
    for obj in env.objects:
        if obj.type.name == 'Texture2D':
            data = obj.read()
            textures.append((data.m_Name, data))
        elif obj.type.name == 'AnimationClip':
            tree = obj.read_typetree()
            clips[tree['m_Name']] = tree
        elif obj.type.name == 'MonoBehaviour':
            tree = obj.read_typetree()
            if '_bytes' in tree:
                payload = bytes(tree['_bytes'])
                if payload.startswith(b'MOC3'):
                    if moc is not None:
                        raise ValueError('multiple Cubism models in one bundle')
                    moc = payload
            elif 'Parameters' in tree and 'FadeInTime' in tree:
                expressions.append((tree['m_Name'], tree))
            elif '_rig' in tree:
                physics = tree
            elif '_unmanagedIndex' in tree and 'Value' in tree:
                key, parameter = parameter_binding(obj)
                if key in bindings and bindings[key] != parameter:
                    raise ValueError('parameter binding collision')
                bindings[key] = parameter
                defaults[parameter] = tree['Value']
    if not moc or not textures:
        raise ValueError('missing Cubism model or textures')
    (destination / (name + '.moc3')).write_bytes(moc)
    texture_files = []
    for index, (_, texture) in enumerate(sorted(textures, key=lambda x: x[0])):
        filename = f'texture_{index:02d}.png'
        texture.image.save(destination / filename)
        texture_files.append(filename)
    expression_files = []
    for index, (label, tree) in enumerate(sorted(expressions, key=lambda x: x[0])):
        safe = re.sub(r'[^a-zA-Z0-9._-]', '-', label).removesuffix('.json').removesuffix('.exp3')
        filename = f'expressions/{index:02d}-{safe or "expression"}.exp3.json'
        write(destination / filename, build_expression3(tree))
        expression_files.append(filename)
    physics_file = name + '.physics3.json' if physics else None
    if physics_file:
        write(destination / physics_file, build_physics3(physics))
    library = convert_motion_library(clips, bindings, publish=True)
    for filename, payload in library['payloads'].items():
        # The UI explicitly controls looping, including originally looping idle clips.
        payload['Meta']['Loop'] = False
        write(destination / filename, payload)
    model_file = name + '.model3.json'
    write(destination / model_file, build_model3(name, texture_files, expression_files,
          physics=physics_file, motions=library['motionGroups']))
    resources = [{'file': str(p.relative_to(destination)), 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                 for p in sorted(destination.rglob('*')) if p.is_file()]
    manifest = {'model': model_file, 'resources': resources, 'totalBytes': sum(x['bytes'] for x in resources),
                'defaults': defaults, 'motions': library['motions'], 'motionReports': library['motionReports'],
                'sourceMotionCount': library['sourceMotionCount'], 'blockedMotionCount': library['blockedMotionCount'],
                'expressionCount': len(expressions), 'physics': bool(physics)}
    write(destination / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--characters', nargs='+', type=int)
    args = parser.parse_args()
    config = json.loads((ROOT / 'config/release-inputs.json').read_text())['environments'][0]
    capture_root = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    catalog_path = capture_root / 'RemoteCatalog/catalog_main.bin'
    metadata_path = ROOT / 'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    if sha256(catalog_path) != CATALOG_SHA256 or sha256(metadata_path) != METADATA_SHA256:
        raise ValueError('source catalog / metadata digest mismatch')
    release = json.loads((ROOT / config['manifest']).read_text())
    if sha256(ROOT / config['manifest']) != config['manifestSha256']:
        raise ValueError('bound release manifest digest mismatch')
    if release['identity']['contentReleaseId'] != config['contentReleaseId'] or release['objects']['remoteCatalog']['sha256'] != CATALOG_SHA256:
        raise ValueError('release identity / resource catalog mismatch')
    capture = json.loads((capture_root / 'capture.json').read_text())
    if (capture['package'], capture['version_name'], capture['version_code']) != ('com.bilibili.sirius', '1.0.1', 25):
        raise ValueError('unexpected source package')
    records = {x['path']: x for x in capture['files']}
    locations = CatalogAdapter().parse(catalog_path)
    metadata = MetadataV39(metadata_path)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    master = ROOT / config['masterRoot']
    master_digest = _master_aggregate([{'logicalName': p.name, 'sha256': sha256(p)} for p in sorted(master.glob('*.json'))])
    if master_digest != release['master']['aggregateSha256']:
        raise ValueError('Master source digest mismatch')
    costumes = json.loads((master / 'MasterCharacterCostume.json').read_text())['_allData']
    models = discover_models(locations.locations, costumes)
    if args.characters:
        models = [x for x in models if x['characterId'] in args.characters]
    story_input = config['storyInputs']
    story_index_path = ROOT / story_input['index']
    if sha256(story_index_path) != story_input['sha256']:
        raise ValueError('story index digest mismatch')
    story_index = json.loads(story_index_path.read_text())
    if story_index['sourceReleaseId'] != config['contentReleaseId']:
        raise ValueError('story release mismatch')
    def story_documents():
        for record in story_index['documents']:
            source = story_index_path.parent / record['path']
            if sha256(source) != record['sha256']:
                raise ValueError('story document digest mismatch')
            yield json.loads(source.read_text())
    characters = story_character_labels(models, json.loads((master / 'MasterText.json').read_text())['_allData'], story_documents())
    public = ROOT / 'site/public/live2d' / config['contentReleaseId']
    public.mkdir(parents=True, exist_ok=True)
    entries = []
    for model in models:
        model_path = model['modelPath']
        entry = dict(model)
        try:
            location = locations.location_for_key('Character/Live2D/' + model_path)
            bundles = [x for x in location.dependencies if x.startswith('character-live2d_')]
            if len(bundles) != 1:
                raise ValueError('expected exactly one model bundle')
            name = bundles[0]
            loc = locations.location_for_key(name)
            files = list((capture_root / 'EncryptedBundles').glob(name[:-7].rsplit('_', 1)[-1] + '_*.bundle'))
            if len(files) != 1:
                raise ValueError('model bundle is not in verified local capture')
            source = files[0]
            record = records.get(source.relative_to(capture_root).as_posix())
            if not record or sha256(source) != record['sha256'] or source.stat().st_size != loc.expected_size:
                raise ValueError('cached bundle digest / size mismatch')
            # Content-addressed output is immutable and safe to cache in the browser.
            folder = f'{model["id"]}-{record["sha256"][:12]}-v1'
            target = public / folder
            if not (target / 'manifest.json').exists():
                env = UnityPy.load(decrypt_header(source.read_bytes(), name, key, seed))
                with tempfile.TemporaryDirectory(dir=public, prefix='.convert-') as temporary:
                    staging = Path(temporary) / 'model'
                    manifest = export_model(env, staging, model_path.rsplit('/', 1)[-1])
                    staging.rename(target)
                del env
                gc.collect()
            manifest = json.loads((target / 'manifest.json').read_text())
            entry.update(state='available', root=f'/live2d/{config["contentReleaseId"]}/{folder}/',
                         bytes=manifest['totalBytes'], motions=len(manifest['motions']),
                         blockedMotions=manifest['blockedMotionCount'], expressions=manifest['expressionCount'],
                         physics=manifest['physics'], sourceSha256=record['sha256'])
        except Exception as exc:
            entry.update(state='unavailable', error=f'{type(exc).__name__}: {exc}')
        entries.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    payload = {'schemaVersion': 2, 'releaseId': config['contentReleaseId'], 'catalogSha256': CATALOG_SHA256,
               'storyIndexSha256': story_input['sha256'], 'characters': characters, 'models': entries}
    verify_live2d_assets(payload, ROOT / 'site/public', config['contentReleaseId'])
    write(ROOT / 'site/src/data/live2d-catalog.json', payload)
    print(json.dumps({'available': sum(x['state'] == 'available' for x in entries), 'total': len(entries)}))


if __name__ == '__main__':
    main()
