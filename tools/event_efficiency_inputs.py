"""Prepare version-bound, local event efficiency inputs without player data."""
import argparse
import hashlib
import json
from pathlib import Path

from tools.scoring_content import bind_scoring_rules
from tools.music_score_runtime import compile_music_score


def prepare(root: Path):
    manifest = json.loads((root / 'scores/index.json').read_text())
    release = manifest['identity']['contentReleaseId']
    master = root / 'master'
    rules = bind_scoring_rules(master, release)
    if rules.get('verificationStatus') != 'reference_compatible':
        raise ValueError(f'Unreviewed scoring inputs: {rules}')
    tables = {p.stem.removeprefix('Master'): json.loads(p.read_text())['_allData']
              for p in master.glob('Master*.json')}
    rows = {r['logicalPath']: r for r in manifest['scores']}
    audio = json.loads((root / 'audio/cri-media-report.json').read_text())
    if audio['identity']['contentReleaseId'] != release:
        raise ValueError('Audio release mismatch')
    durations = {}
    for row in audio['files']:
        if row.get('ok') and row.get('trackId') and len(row.get('streams', [])) == 1:
            stream = row['streams'][0]
            durations[row['trackId']] = stream['samples'] / stream['sample_rate']
    charts = []
    for music in tables['LiveMusic']:
        for difficulty in ['easy', 'normal', 'hard', 'expert']:
            score_id = music[f'_{difficulty}ID']
            score = next(r for r in tables['LiveMusicScore'] if r['_id'] == score_id)
            logical = score['_musicScoreTextFileName'] + '.bytes'
            source = rows[logical]
            payload = (root / 'scores' / source['file']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != source['sha256']:
                raise ValueError(f'Chart hash mismatch: {logical}')
            charts.append(dict(compile_music_score(payload), id=f'music-chart-{score_id}',
                               trackId=f"music-{music['_id']}", difficulty=difficulty, sourceReleaseId=release))
    names = {r['_id']: r['_japanese'] for r in tables['Text']}
    for chart in charts:
        chart['audioDuration'] = durations.get(chart['trackId'])
        if chart['audioDuration'] is None:
            raise ValueError(f"Missing song audio duration: {chart['trackId']}")
    keep = set(rules['tables']) | {'LiveScoreRank', 'LiveChallengePoint', 'ChallengeMusic',
                                  'LiveMusicBoostBonus', 'ChallengeMusicBoostBonus',
                                  'LiveEventPoint', 'LiveEventReward', 'ChallengeLiveEventPoint',
                                  'ChallengeLiveEventReward', 'EventAchievementReward',
                                  'EventAchievementLoopReward', 'Reward'}
    return {'sourceReleaseId': release, 'rules': rules, 'tables': {k: tables[k] for k in keep},
            'names': names, 'charts': charts,
            'inputHashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in master.glob('Master*.json') if p.stem.removeprefix('Master') in keep}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f"{len(result['charts'])} charts; {result['sourceReleaseId']}; reference model")
