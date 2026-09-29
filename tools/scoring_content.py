"""Bind reference calculations to content without inheriting a new client's audit.

Only unchanged scoring tables are supported. LiveMusic may expose additional
songs already described by the audited score table, using known attribute and
mission values. A different formula/skill/event table remains unavailable.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tools.build_formal_scoring_rules import ROOT, TABLES

BASELINE = ROOT / 'site/src/data/formal-scoring-rules.json'


def bind_scoring_rules(master: Path, release: str, baseline=None):
    base = baseline or json.loads(BASELINE.read_text())
    unavailable = {'schemaVersion': 1, 'sourceReleaseId': release,
                   'verificationStatus': 'unavailable'}
    rows, hashes = {}, {}
    for name in TABLES:
        path = master / f'Master{name}.json'
        if not path.is_file():
            return {**unavailable, 'reason': 'missing_scoring_inputs'}
        raw = path.read_bytes()
        rows[name] = json.loads(raw)['_allData']
        hashes[f'Master{name}'] = hashlib.sha256(raw).hexdigest()
        if name != 'LiveMusic' and hashes[f'Master{name}'] != base['masterSha256'][f'Master{name}']:
            return {**unavailable, 'reason': 'changed_scoring_table', 'table': name}
    fields = tuple(base['tables']['LiveMusic'][0])
    songs = [{key: row[key] for key in fields} for row in rows['LiveMusic']]
    prior = {row['_id']: row for row in base['tables']['LiveMusic']}
    current = {row['_id']: row for row in songs}
    if len(current) != len(songs) or any(current.get(key) != row for key, row in prior.items()):
        return {**unavailable, 'reason': 'changed_song_rules'}
    score_songs = {row['_id'] // 100 for row in base['tables']['LiveMusicScore']}
    tags = {tag for row in prior.values() for tag in row['_bestMusicTagIDs']}
    for row in songs:
        if row['_id'] not in score_songs or not set(row['_bestMusicTagIDs']).issubset(tags):
            return {**unavailable, 'reason': 'unsupported_song_rules'}
        for key in fields:
            if key not in ('_id', '_bestMusicTagIDs') and row[key] not in {r[key] for r in prior.values()}:
                return {**unavailable, 'reason': 'unsupported_song_rules'}
    if release == base['sourceReleaseId']:
        return deepcopy(base) if hashes == base['masterSha256'] else {**unavailable, 'reason': 'audit_input_mismatch'}
    rules = deepcopy(base)
    rules.update(sourceReleaseId=release, verificationStatus='reference_compatible', masterSha256=hashes,
                 referenceProfile={'sourceReleaseId': base['sourceReleaseId'],
                                   'nativeSha256': base['nativeSha256'],
                                   'dataCompatibility': 'scoring_tables_matched',
                                   'currentGameplayVerified': False})
    # Preserve the native audit's original identity. Do not relabel old code as
    # current code just because the data can be evaluated by the same model.
    rules['tables']['LiveMusic'] = songs
    rules['capabilities']['formationPower'] = 'reference_model_estimate'
    return rules


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(bind_scoring_rules(args.master, args.release), ensure_ascii=False, separators=(',', ':')) + '\n')
