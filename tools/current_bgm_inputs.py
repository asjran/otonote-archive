"""Refresh all catalog BGM payloads and reuse only identical verified sources."""
import copy
from pathlib import Path
import tempfile
from tools.global_remote_sync import read_json, write_json, file_hash
from tools.build_remote_global_inputs import ROOT, contained
from tools.current_input_cache import verified_link


def extract_bgm(resources, source, previous, output):
    from tools.import_bgm_audio import bgm_assets, find_executable, process_acb, process_split_acb, discover_split_acb, process_unity_acb, discover_unity_acb, CURRENT_USM_KEY
    from tools.bgm_catalog import read_bgm_inputs
    prior = read_bgm_inputs(previous, ROOT)
    old = {r['cue_sheet_name']: r for r in prior[1]['files']} if prior else {}
    records = []
    ffmpeg = vgmstream = None
    for asset, loc in bgm_assets(resources.catalog.locations):
        cue = asset.primary_key.rsplit('/', 1)[-1]
        # Raw CRI names can remain stable across releases; compare actual bytes.
        payload = resources.get(loc)
        sha = file_hash(payload)
        record = copy.deepcopy(old.get(cue))
        if record and record['sha256'] == sha:
            for stream in record['streams']:
                verified_link(contained(prior[0].parent, stream['output']), contained(output, stream['output']), stream['sha256'])
        else:
            ffmpeg = ffmpeg or find_executable(None, ('ffmpeg', '/opt/homebrew/bin/ffmpeg'))
            vgmstream = vgmstream or find_executable(None, ('vgmstream-cli', '/opt/homebrew/bin/vgmstream-cli'))
            if loc.provider_id.endswith('.CriResourceProvider'):
                record = process_acb(payload, sha, output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg)
            else:
                with tempfile.TemporaryDirectory() as folder:
                    (Path(folder) / Path(loc.primary_key).name).symlink_to(payload)
                    candidates = discover_split_acb(Path(folder))
                    if candidates:
                        if len(candidates) != 1: raise ValueError('ambiguous BGM payload')
                        candidate = candidates[0]; candidate.source = payload
                        record = process_split_acb(candidate, output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg, process_acb)
                    else:
                        embedded = discover_unity_acb(Path(folder))
                        if len(embedded) != 1: raise ValueError('missing unique embedded BGM')
                        record = process_unity_acb(embedded[0], output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg, process_acb)
            record.pop('hca_key', None)
            if not record.get('ok') or not record.get('streams'): raise ValueError('BGM validation failed: ' + cue)
            for stream in record['streams']:
                path = Path(stream['output'])
                stream.update(output=str(path.relative_to(output)), sha256=file_hash(path))
        record.update(cue_sheet_name=cue, assetPath=asset.internal_id, source=loc.primary_key)
        records.append(record)
    write_json(output / 'bgm-audio-report.json', {'schemaVersion': 1, 'complete': True,
        'identity': {k: source[k] for k in ('region', 'channel', 'contentReleaseId')},
        'catalogSha256': resources.report['catalogSha256'], 'files': records})
    return sum(len(r['streams']) for r in records)
