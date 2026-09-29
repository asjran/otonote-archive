"""Download and decode only the current release's Master-bound song bundles.

Keeps source receipts, decoded FLAC, and an identity-bound report for rebuilds.
Existing verified inputs are reused; a failed download or decode stops the batch.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analysis/crypto'))
from tools.download_global_public_asset import CATALOG, CATALOG_SHA256, download
from tools.release_preflight import digest, load_plan, check_environment
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from extract_cri_media import CURRENT_USM_KEY, find_executable, process_acb
from extract_split_acb import discover_split_acb, process_split_acb
from extract_unity_acb import discover_unity_acb, process_unity_acb


def song_bundles(master_root, locations, sound_field='_musicSoundID'):
    def rows(name):
        return json.loads((master_root / f'{name}.json').read_text())['_allData']
    sounds = {x['_id']: x for x in rows('MasterSound')}
    cues = {x['_id']: x for x in rows('MasterSoundCueSheet')}
    result = []
    for track in rows('MasterLiveMusic'):
        sound = sounds[track[sound_field]]
        cue = cues[sound['_soundCueSheetID']]['_cueSheetName']
        if sound['_cueName'] != cue:
            raise ValueError('Master cue mismatch')
        pattern = re.compile(r'^cri_assets_cri_sound_' + re.escape(cue.lower()) + r'_[a-f0-9]{32}\.bundle$')
        matches = [x for x in locations if pattern.fullmatch(x.primary_key)
                   and x.provider_id.endswith('.AssetBundleProvider')]
        if len(matches) != 1:
            raise ValueError(f'{cue}: expected one exact song bundle')
        result.append((track['_id'], cue, matches[0]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--variant', choices=('full', 'preview'), default='full')
    args = parser.parse_args()
    source = next(x for x in load_plan(ROOT / 'config/release-inputs.json') if x['id'] == 'global-production')
    if check_environment(source)['status'] != 'passed' or digest(CATALOG) != CATALOG_SHA256:
        raise ValueError('Formal release inputs failed verification')
    bound = song_bundles(ROOT / source['masterRoot'], CatalogAdapter().parse(CATALOG).locations,
                         '_jingleSoundID' if args.variant == 'preview' else '_musicSoundID')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_executable(None, ('ffmpeg', '/opt/homebrew/bin/ffmpeg'))
    vgmstream = find_executable(None, ('vgmstream-cli', '/opt/homebrew/bin/vgmstream-cli'))
    records = []
    for index, (track_id, cue, location) in enumerate(bound[:args.limit], 1):
        bundle = output / 'bundles' / location.primary_key
        receipt = bundle.with_suffix('.bundle.json')
        if bundle.exists():
            audit = json.loads(receipt.read_text())
            if audit['catalogSha256'] != CATALOG_SHA256 or audit['bundle'] != location.primary_key or digest(bundle) != audit['sha256'] or bundle.stat().st_size != location.expected_size:
                raise ValueError(f'{cue}: cached bundle failed verification')
        else:
            download(location.primary_key, bundle)
        cached = output / 'records' / f'{track_id}.json'
        if cached.exists():
            record = json.loads(cached.read_text())
            if record['sha256'] != digest(bundle) or record['cue_sheet_name'] != cue or not record['ok']:
                raise ValueError(f'{cue}: invalid saved decode')
            for stream in record['streams']:
                if digest(Path(stream['output'])) != stream['sha256']:
                    raise ValueError(f'{cue}: decoded audio digest mismatch')
        else:
            # Discover only this bundle, avoiding rescans of earlier decoded inputs.
            import tempfile
            with tempfile.TemporaryDirectory(dir=output, prefix='.discover-') as temporary:
                (Path(temporary) / bundle.name).symlink_to(bundle)
                candidates = discover_split_acb(Path(temporary))
                embedded = [] if candidates else discover_unity_acb(Path(temporary))
            candidates = candidates or embedded
            if len(candidates) != 1 or candidates[0].cue_sheet != cue:
                raise ValueError(f'{cue}: unique ACB object not found')
            candidate = replace(candidates[0], source=bundle)
            decoder = process_unity_acb if embedded else process_split_acb
            record = decoder(candidate, output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg, process_acb)
            record.pop('hca_key', None)
            if not record['ok'] or len(record.get('streams', [])) != 1:
                raise ValueError(f'{cue}: decode failed: {record.get("error")}')
            for stream in record['streams']:
                stream['sha256'] = digest(Path(stream['output']))
            record['trackId'] = f'music-{track_id}'
            cached.parent.mkdir(exist_ok=True)
            cached.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        records.append(record)
        print(f'[{index}/{min(args.limit or len(bound), len(bound))}] {cue}: {record["streams"][0]["duration_seconds"]:.2f}s validated', flush=True)
    # Reports remain portable when the repository is moved.
    for record in records:
        record['source'] = str(Path(record['source']).relative_to(output))
        for stream in record['streams']:
            stream['output'] = str(Path(stream['output']).relative_to(output))
    report = {'schemaVersion': 1, 'identity': {k: source[k] for k in ('region','channel','contentReleaseId')},
              'catalogSha256': CATALOG_SHA256, 'files': records, 'complete': len(records) == len(bound)}
    report_path = output / ('cri-media-report.json' if report['complete'] else 'sample-report.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Report: {report_path}', flush=True)


if __name__ == '__main__':
    main()
