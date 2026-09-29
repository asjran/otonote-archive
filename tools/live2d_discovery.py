"""Discover every catalog model; Master costumes enrich, rather than limit, coverage."""
from __future__ import annotations
import hashlib
import re


def discover_models(locations, costumes):
    by_path = {row['_live2dPath']: row for row in costumes}
    paths = sorted({loc.primary_key.removeprefix('Character/Live2D/') for loc in locations
                    if loc.primary_key.startswith('Character/Live2D/')})
    # Keep missing Master references visible as unavailable entries.
    paths = sorted(set(paths) | set(by_path))
    models = []
    for path in paths:
        costume = by_path.get(path)
        family = path.split('/')[0]
        main = re.fullmatch(r'(\d+)_(adv|live)', family)
        character = costume['_characterID'] if costume else int(main[1]) if main else family
        models.append({
            'id': str(costume['_id']) if costume else 'asset-' + hashlib.sha256(path.encode()).hexdigest()[:16],
            'characterId': character, 'costumeId': costume['_costumeID'] if costume else None,
            'isDefault': costume['_isDefault'] if costume else False,
            'modelPath': path, 'category': 'member' if isinstance(character, int) else 'story',
            'usage': 'live' if main and main[2] == 'live' else 'story',
            'variant': 'still' if path.split('/')[-1].endswith('_still') else 'model',
            'source': 'master-costume' if costume else 'resource-catalog',
        })
    return models


def story_character_labels(models, master_texts, documents):
    """Use only explicit asset-to-speaker links and localized source text."""
    families = {m['characterId'] for m in models if m['category'] == 'story'}
    aliases = {family: set() for family in families}
    texts = {}
    for document in documents:
        for row in document['texts']:
            key = row['_id']
            if key.startswith('adv_') and 'script' not in key:
                texts.setdefault(key, row)
        for row in document['root']['Collection']:
            family = row.get('TargetAssetName', '').split('/')[0]
            if family in aliases and row.get('TargetName'):
                aliases[family].add(row['TargetName'])
    master = {row['_id'].lower(): row for row in master_texts}
    result = []
    for family in sorted(families):
        slug = family.removeprefix('sub_')
        full = master.get('character_name_' + slug)
        exact = texts.get('adv_' + slug)
        rows = [full or exact] if full or exact else [texts['adv_' + a] for a in sorted(aliases[family]) if 'adv_' + a in texts]
        localized = {locale: ' / '.join(dict.fromkeys(r[field] for r in rows if r.get(field))) or slug
                     for locale, field in [('zh-CN', '_simplifiedChinese'), ('en', '_english')]}
        result.append({'id': family, 'names': localized, 'category': 'story',
                       'nameTextIds': [r['_id'] for r in rows], 'aliases': sorted(aliases[family])})
    return result
