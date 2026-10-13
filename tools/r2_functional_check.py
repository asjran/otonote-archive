"""Check release-bound public capabilities before upload; preserve optional degradation."""
import argparse
import hashlib
import json
from pathlib import Path
import re

DOCUMENTS = ('projection/catalog.json', 'projection/game-modes.json', 'projection/game-database.json',
             'supplemental/formal-scoring-rules.json', 'supplemental/scoring-compatibility.json')


def read(path, limit=16 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('missing or unsafe functional input')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('functional input exceeds limit')
    return raw


def check(store, region):
    store = Path(store).resolve()
    pointer = json.loads(read(store / ('current.json' if region == 'global' else 'jp/current.json'), 4096))
    match = re.fullmatch(r'/content/releases/([a-f0-9]{24})/manifest.json', pointer.get('manifest', ''))
    if not match:
        raise ValueError('invalid functional release pointer')
    release = store / 'releases' / match[1]
    if release.is_symlink():
        raise ValueError('linked functional release')
    raw = read(release / 'manifest.json', 4 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != pointer.get('sha256'):
        raise ValueError('functional manifest digest mismatch')
    manifest = json.loads(raw)
    source_id = pointer.get('contentReleaseId')
    if (manifest.get('region') != region or manifest.get('contentReleaseId') != source_id
            or manifest.get('root') != '/content/releases/' + match[1] + '/'
            or not isinstance(source_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}', source_id)
            or set(manifest.get('locales', {})) != {'en', 'zh-CN'}):
        raise ValueError('functional manifest identity mismatch')
    locales = {}
    for locale in ('en', 'zh-CN'):
        documents = {}
        for name in DOCUMENTS:
            entry = manifest['locales'][locale]['files'][name]
            relative = entry['path']
            if (not isinstance(relative, str) or not relative.startswith(locale + '/')
                    or any(part in ('', '.', '..') or part.startswith('.') for part in relative.split('/'))):
                raise ValueError('unsafe functional document path')
            path = release / relative
            if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.resolve().is_relative_to(release):
                raise ValueError('linked functional document')
            raw = read(path)
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('functional document digest mismatch')
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError('invalid functional document')
            identity = document.get('release', {}).get('id') if name == DOCUMENTS[0] else document.get('sourceReleaseId')
            # Unavailable scoring diagnostics may omit source identity. Their
            # containing immutable manifest still binds them to this release.
            optional_unavailable = name == DOCUMENTS[-1] and document.get('status') == 'unavailable' and identity is None
            if identity != source_id and not optional_unavailable:
                raise ValueError('functional document release mismatch')
            documents[name] = document
        catalog, modes, database, rules, scoring = (documents[name] for name in DOCUMENTS)
        context = {'contentReleaseId': source_id, 'region': region, 'channel': 'production', 'locale': locale}
        if catalog.get('projectionContext') != context:
            raise ValueError('functional catalog context mismatch')
        for name in ('memberCards', 'supportCards', 'musicTracks'):
            if not isinstance(catalog.get(name), list) or not catalog[name]:
                raise ValueError('required catalog capability absent')
        if not isinstance(modes.get('events'), dict) or not isinstance(modes['events'].get('records'), list) or not isinstance(database.get('skills'), list) or not database['skills']:
            raise ValueError('required event or skill contract absent')
        if scoring.get('status') not in ('compatible', 'partial', 'unavailable') or not isinstance(scoring.get('issues'), list):
            raise ValueError('invalid scoring diagnostic')
        if scoring['status'] == 'compatible' and (scoring['issues'] or type(scoring.get('checks')) is not int or scoring['checks'] <= 0):
            raise ValueError('empty or contradictory scoring success')
        if rules.get('verificationStatus') not in ('code_audited', 'reference_compatible', 'unavailable'):
            raise ValueError('unknown scoring verification status')
        # Optional rules do not block catalog/event publication. No gameplay
        # correctness is inferred from successful reference compatibility.
        locales[locale] = {'memberCards': len(catalog['memberCards']), 'supportCards': len(catalog['supportCards']),
                           'events': len(modes['events']['records']), 'skills': len(database['skills']),
                           'scoring': scoring['status'], 'scoringIssues': len(scoring['issues']),
                           'verificationStatus': rules['verificationStatus'], 'gameplayVerified': False}
    return {'schemaVersion': 1, 'region': region, 'releaseId': match[1], 'contentReleaseId': source_id,
            'status': 'passed', 'locales': locales,
            'limitations': ['formal_gameplay_not_verified']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--region', choices=('global', 'jp'), required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.store, args.region), separators=(',', ':')))


if __name__ == '__main__':
    main()
