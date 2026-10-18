"""Build byte-bound scene playback profiles from the verified Global client prefabs.

The input packages and decoder material stay external. Output contains camera
settings, member/layer bindings and resource digests, never decoded game assets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def member_alias(name):
    return re.split(r'[_\s]', name.strip().lower())[0]


def bone_partition(skeleton, aliases):
    """Use authored bone and slot names, hierarchy and constraint targets together."""
    bones = skeleton['bones']; index = {b['name']: i for i, b in enumerate(bones)}
    owners = [None] * len(bones)
    def named(name):
        name = name.lower()
        matches = {cid for alias, cid in aliases.items() if (re.search(r'(?<![a-z])'+re.escape(alias)+r'(?![a-z])', name) if alias.isascii() else alias in name)}
        return next(iter(matches)) if len(matches) == 1 else None
    for i, bone in enumerate(bones): owners[i] = named(bone['name'])
    hints = {}
    for slot in skeleton['slots']:
        cid = named(slot['name']) or named(slot.get('attachment', ''))
        if cid is not None: hints.setdefault(index[slot['bone']], set()).add(cid)
    for i, values in hints.items():
        if i != 0 and len(values) == 1 and owners[i] is None: owners[i] = next(iter(values))
    children = {i: [] for i in range(len(bones))}
    for i, bone in enumerate(bones):
        if bone.get('parent') in index: children[index[bone['parent']]].append(i)
    def descendant_hints(i):
        values = {owners[i]} if owners[i] is not None else set()
        for child in children[i]: values.update(descendant_hints(child))
        return values
    evidence = [descendant_hints(i) for i in range(len(bones))]
    for _ in range(len(bones) + 1):
        previous = list(owners)
        for i, bone in enumerate(bones):
            if i == 0 or owners[i] is not None: continue
            parent = index.get(bone.get('parent'))
            values = evidence[i]
            if parent is not None and owners[parent] is not None: owners[i] = owners[parent]
            elif len(values) == 1: owners[i] = next(iter(values))
        for kind in ('ik', 'transform', 'path'):
            for constraint in skeleton.get(kind, []):
                values = {owners[index[b]] for b in constraint.get('bones', []) if owners[index[b]] is not None}
                target = index.get(constraint.get('target'))
                if target not in (None, 0) and owners[target] is None and len(values) == 1:
                    owners[target] = next(iter(values))
        if owners == previous: break
    slots = [named(slot['name']) or owners[index[slot['bone']]] for slot in skeleton['slots']]
    return {'bones': owners, 'slots': slots}


def make_profile(spot, components, scene, labels, supplemental=()):
    settings = next(c['fields'] for c in components if 'fieldOfView' in c['fields'])
    anchors = [c for c in components if '_characterId' in c['fields']]
    expected = set(spot['_characterIds'])
    corrections = []
    labels = {**labels, **{c['id']: {**c, 'tokens': []} for c in supplemental}}
    aliases = {c['alias']: c['id'] for c in supplemental}
    for a in anchors:
        cid = a['fields']['_characterId']
        if cid not in expected:
            corrections.append({'unlistedAnchor': a['name'], 'nativeId': cid, 'webActorId': aliases.get(member_alias(a['name'])), 'reason': 'not listed in MasterHomeSpot; no Master identity reassignment'}); continue
        aliases[member_alias(a['name'])] = cid
    characters = [{'id': cid, 'name': labels[cid]['name'], 'nameEn': labels[cid]['nameEn'], 'nodes': []} for cid in [*spot['_characterIds'], *[c['id'] for c in supplemental]]]
    by_id = {c['id']: c for c in characters}
    by_node = {n['id']: n for n in scene['nodes']}
    controllers = {c['gameObjectId']: c for c in components if '_animation' in c['fields']}
    shared = {}
    for node in scene['nodes']:
        if not node.get('spine'): continue
        current = node; controller = None
        while current:
            controller = controllers.get(current['gameObjectId'])
            if controller: break
            current = by_node.get(current['parent'])
        name = (controller['name'] if controller else node['name']).lower()
        ids = sorted({cid for alias, cid in aliases.items() if alias in name}, key=str)
        for cid in ids: by_id[cid]['nodes'].append(node['id'])
        if len(ids) > 1:
            shared[node['id']] = {a: cid for a, cid in aliases.items() if cid in ids}
            for cid in ids:
                for token in labels[cid]['tokens']:
                    if token: shared[node['id']][token.lower()] = cid
    if any(not c['nodes'] for c in characters): raise ValueError(f'{spot["_id"]}: unbound member')
    xyz = lambda key: [settings[key][k] for k in 'xyz']
    target, base, start = xyz('originalOffset'), xyz('defaultPositionOffset'), xyz('zoomOutStartPosition')
    forward = [t - b for t, b in zip(target, base)]; length = math.sqrt(sum(v*v for v in forward))
    if not length: raise ValueError('zero camera look direction')
    end = [b - f / length * settings['orbitRatio'] for b, f in zip(base, forward)]
    flip = lambda v: [round(v[0], 8), round(v[1], 8), round(-v[2], 8)]
    background = next(n for n in scene['nodes'] if n.get('backgroundRoot') or n['name'] == spot['_backgroundAssetPath'].split('/')[-1])
    profile = {'id': spot['_id'], 'folders': [], 'camera': {
        'fov': max(settings['zoomMinFov'], min(settings['zoomMaxFov'], settings['fieldOfView'])),
        'start': flip(start), 'end': flip(end), 'target': flip(target),
        'duration': settings['zoomOutDuration'], 'ease': settings['zoomOutEase']},
        'background': {'node': background['id'], 'position': xyz('backgroundPosition'),
                       'rotation': xyz('backgroundRotation'), 'scale': xyz('backgroundScale')},
        'characters': characters, 'partitions': {}, 'packages': []}
    return profile, shared, corrections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources-root', type=Path, required=True)
    parser.add_argument('--package-root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from analysis.crypto.decrypt_global_formal_scores import (MetadataV39, field_bytes, decrypt_header,
        KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE, METADATA_SHA256, CATALOG_SHA256, UnityPy)
    from tools.resource_pipeline.catalog_adapter import CatalogAdapter
    r = args.resources_root
    master = r/'input/global/decrypted/2026-09-24-v1.0.1-25/master-json'
    load = lambda name: json.loads((master/(name+'.json')).read_text())['_allData']
    texts = {t['_id']: t for t in load('MasterText')}
    labels = {c['_id']: {'name': texts[c['_nameTextID']]['_simplifiedChinese'],
                           'nameEn': texts[c['_nameTextID']]['_english'],
                           'tokens': [texts[c['_shortNameTextID']][lang] for lang in ('_japanese', '_simplifiedChinese')]} for c in load('MasterCharacter')}
    # Visible supporting actors have no current MasterCharacter identity. Keep
    # independent web IDs; in particular Kanata's stale native ID 6 is NOT Uika.
    supplemental = {
        30002: [{'id': 'scene-manager', 'alias': 'manager', 'name': '像素小人', 'nameEn': 'Pixel character'}],
        30003: [{'id': 'scene-marukun', 'alias': 'marukun', 'name': '白色吉祥物', 'nameEn': 'White mascot'}],
        40001: [{'id': 'scene-kanata', 'alias': 'kanata',
                 'name': texts['Character_Name_Kanata']['_simplifiedChinese'],
                 'nameEn': texts['Character_Name_Kanata']['_english']}],
    }
    metadata = r/'input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat'
    if hashlib.sha256(metadata.read_bytes()).hexdigest() != METADATA_SHA256: raise ValueError('unverified metadata')
    m = MetadataV39(metadata); key = field_bytes(m, KEY_FIELD_USAGE, 16); seed = field_bytes(m, NONCE_SEED_FIELD_USAGE, 8)
    catalog = r/'input/global/device-files/2026-09-24-v1.0.1-25/RemoteCatalog/catalog_main.bin'
    if hashlib.sha256(catalog.read_bytes()).hexdigest() != CATALOG_SHA256: raise ValueError('unverified catalog')
    locations = {e.primary_key: e for e in CatalogAdapter().parse(catalog).locations}
    acquisition = json.loads((r/'input/global/remote-immersive/2026-09-27-catalog-39b5d81f/manifest.json').read_text())
    sources = {e['bundle']: e for e in acquisition['files']}
    packages = {}
    for root in args.package_root:
        for path in sorted(root.glob('*/manifest.json')):
            manifest = json.loads(path.read_text())
            if manifest.get('sceneId'): packages.setdefault(manifest['sceneId'], []).append((path.parent, manifest))
    result, report, verified_files = {}, [], set()
    for spot in load('MasterHomeSpot'):
        entry = sources[locations[spot['_situationAssetPath']].dependencies[0]]
        payload = (r/entry['path']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry['sha256']: raise ValueError('native prefab digest mismatch')
        env = UnityPy.load(decrypt_header(payload, entry['bundle'], key, seed))
        names = {o.path_id: o.read().m_Name for o in env.objects if o.type.name == 'GameObject'}
        components = []
        for o in env.objects:
            if o.type.name != 'MonoBehaviour': continue
            tree = o.read_typetree()
            if any(k in tree for k in ('fieldOfView', '_characterId', '_animation')):
                go = tree['m_GameObject']['m_PathID']
                components.append({'name': names[go], 'gameObjectId': str(go), 'fields': tree})
        variants = [(p, m) for p, m in packages.get(spot['_id'], []) if any(s['sha256'] == entry['sha256'] for s in m['sources'])]
        if not variants: raise ValueError(f'{spot["_id"]}: no source-bound browser package')
        profile = None; corrections = []; shared = {}
        for path, manifest in variants:
            for record in manifest['files']:
                file = (path/record['path']).resolve(); binding = (file, record['sha256'])
                if binding in verified_files: continue
                payload = file.read_bytes()
                if len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest() != record['sha256']: raise ValueError(f'invalid resource: {file.name}')
                verified_files.add(binding)
            scene = json.loads((path/'scene.json').read_text())
            candidate, joint, correction = make_profile(spot, components, scene, labels, supplemental.get(spot['_id'], ()))
            if profile is None:
                profile, shared, corrections = candidate, joint, correction
                for node_id, aliases in shared.items():
                    node = next(n for n in scene['nodes'] if n['id'] == node_id)
                    if node.get('spineFormat') == 'binary': raise ValueError('binary joint skeleton needs explicit parsing')
                    skeleton = json.loads((path/(node['spine']+'.json')).read_text())
                    profile['partitions'][node_id] = bone_partition(skeleton, aliases)
                    visible = set(profile['partitions'][node_id]['slots']) - {None}
                    for character in profile['characters']:
                        if character['id'] not in visible:
                            character['nodes'] = [n for n in character['nodes'] if n != node_id]
            else:
                for character in candidate['characters']:
                    character['nodes'] = [n for n in character['nodes'] if n not in profile['partitions'] or character['id'] in profile['partitions'][n]['slots']]
                if candidate['characters'] != profile['characters']: raise ValueError('variant member binding differs')
            if path.name not in profile['folders']: profile['folders'].append(path.name)
            files = {rec['path']: rec['sha256'] for rec in manifest['files'] if rec['path'] != 'poster.webp'}
            if files not in profile['packages']: profile['packages'].append(files)
        profile['sourcePrefabSha256'] = entry['sha256']; result[str(spot['_id'])] = profile
        report.append({'id': spot['_id'], 'members': len(profile['characters']), 'sharedSkeletons': len(shared),
                       'variants': len(profile['packages']), 'unlistedAnchors': corrections, 'supplementalActors': [c['id'] for c in supplemental.get(spot['_id'], ())]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('{\n'+',\n'.join('  '+json.dumps(k)+':'+json.dumps(v, ensure_ascii=False, separators=(',', ':')) for k, v in result.items())+'\n}\n')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({'metadataSha256': METADATA_SHA256, 'catalogSha256': CATALOG_SHA256,
                                     'verifiedFiles': len(verified_files), 'scenes': report}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'scenes': len(result), 'members': sum(s['members'] for s in report),
                      'sharedSkeletons': sum(s['sharedSkeletons'] for s in report), 'verifiedFiles': len(verified_files)}))


if __name__ == '__main__': main()
