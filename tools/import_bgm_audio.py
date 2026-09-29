"""Decode catalog-bound BGM assets and produce a portable, versioned receipt.

Uses the captured production catalog, reuses matching device cache files and
downloads only its exact public asset locations. No game API requests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analysis/crypto'))

from tools.download_global_public_asset import CATALOG, CATALOG_SHA256, HOST, download, public_root
from tools.release_preflight import digest, load_plan, check_environment
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.transport import HttpRequest, HttpTransport
from extract_cri_media import CURRENT_USM_KEY, find_executable, process_acb
from extract_split_acb import discover_split_acb, process_split_acb
from extract_unity_acb import discover_unity_acb, process_unity_acb


def bgm_assets(locations):
    """Only actual BGM ACB assets; omit test bundles and unrelated sound effects."""
    result = []
    by_key = {x.primary_key: x for x in locations}
    for asset in locations:
        path = asset.internal_id.lower()
        if (asset.resource_type.endswith('CriAtomAcbAsset')
                and ('/bgm/' in path or path.endswith(('/bgm.acb', '/ambientbgm.acb')))):
            dependencies = [by_key[key] for key in asset.dependencies if key in by_key]
            raw = [x for x in dependencies if x.provider_id.endswith('.CriResourceProvider')]
            bundle = [x for x in dependencies if x.provider_id.endswith('.AssetBundleProvider')
                      and x.primary_key.startswith('cri_assets_')]
            targets = raw or bundle
            if len(targets) != 1:
                raise ValueError(f'BGM asset has ambiguous payload: {asset.primary_key}')
            result.append((asset, targets[0]))
    return sorted(result, key=lambda x: x[0].primary_key)


def fetch_payload(location, output):
    """Pin cached/downloaded raw CRI bytes to an exact catalog receipt."""
    receipt = output.with_suffix(output.suffix + '.json')
    if output.exists():
        audit = json.loads(receipt.read_text())
        if (audit['catalogSha256'] != CATALOG_SHA256 or audit['bundle'] != location.primary_key
                or audit['sha256'] != digest(output) or output.stat().st_size != location.expected_size):
            raise ValueError('BGM cached payload mismatch')
        return
    if location.provider_id.endswith('.AssetBundleProvider'):
        download(location.primary_key, output)
        return
    parsed = urlsplit(location.internal_id)
    if (parsed.scheme != 'https' or parsed.hostname != 'dummy.net'
            or parsed.path != '/asset/Android/' + location.primary_key
            or not re.fullmatch(r'cri_assets_cri/sound/[a-z0-9_]+', location.primary_key)):
        raise ValueError('Unexpected raw BGM catalog path')
    name = Path(location.primary_key).name
    cache = CATALOG.parent.parent / 'Addressables'
    matches = list(cache.glob(f'*/*/{name}'))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        part = Path(temp) / 'payload'
        if len(matches) == 1 and matches[0].stat().st_size == location.expected_size:
            import shutil
            shutil.copyfile(matches[0], part)
            origin = 'device-cache'
        else:
            transport = HttpTransport(allowed_hosts=(HOST,), connect_timeout_seconds=20,
                                      read_timeout_seconds=60, max_response_bytes=location.expected_size)
            with part.open('wb') as stream:
                response = transport.download(HttpRequest('GET', public_root() + parsed.path), stream)
            if response.status != 200 or response.byte_size != location.expected_size:
                raise ValueError('BGM download size/status mismatch')
            origin = 'public-patch'
        if part.read_bytes()[:4] != b'@UTF':
            raise ValueError('BGM payload is not CRI ACB')
        audit = {'catalogSha256': CATALOG_SHA256, 'bundle': location.primary_key,
                 'sha256': digest(part), 'byteSize': part.stat().st_size, 'origin': origin}
        part.replace(output)
        receipt.write_text(json.dumps(audit, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    source = load_plan(ROOT / 'config/release-inputs.json')[0]
    if check_environment(source)['status'] != 'passed' or digest(CATALOG) != CATALOG_SHA256:
        raise ValueError('Release/catalog verification failed')
    assets = bgm_assets(CatalogAdapter().parse(CATALOG).locations)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_executable(None, ('ffmpeg', '/opt/homebrew/bin/ffmpeg'))
    vgmstream = find_executable(None, ('vgmstream-cli', '/opt/homebrew/bin/vgmstream-cli'))
    records = []
    for index, (asset, location) in enumerate(assets[:args.limit], 1):
        cue = asset.primary_key.rsplit('/', 1)[-1]
        payload = output / 'bundles' / Path(location.primary_key).name
        fetch_payload(location, payload)
        saved = output / 'records' / f'{cue}.json'
        if saved.exists():
            record = json.loads(saved.read_text())
            if record['sha256'] != digest(payload) or not record.get('ok'):
                raise ValueError(f'{cue}: invalid decode cache')
            for stream in record['streams']:
                if digest(output / stream['output']) != stream['sha256']:
                    raise ValueError(f'{cue}: invalid decoded audio')
        else:
            if location.provider_id.endswith('.CriResourceProvider'):
                record = process_acb(payload, digest(payload), output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg)
            else:
                with tempfile.TemporaryDirectory(dir=output) as temp:
                    (Path(temp) / payload.name).symlink_to(payload)
                    candidates = discover_split_acb(Path(temp))
                    if candidates:
                        candidate = candidates[0]
                        candidate.source = payload
                        record = process_split_acb(candidate, output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg, process_acb)
                    else:
                        embedded = discover_unity_acb(Path(temp))
                        if len(embedded) != 1:
                            raise ValueError(f'{cue}: no unique embedded ACB')
                        record = process_unity_acb(embedded[0], output, output / '_work', CURRENT_USM_KEY, vgmstream, ffmpeg, process_acb)
            record.pop('hca_key', None)
            if not record.get('ok') or not record.get('streams'):
                raise ValueError(f'{cue}: audio validation failed')
            record.update(cue_sheet_name=cue, assetPath=asset.internal_id,
                          source=str(payload.relative_to(output)))
            for stream in record['streams']:
                path = Path(stream['output'])
                stream['sha256'] = digest(path)
                stream['output'] = str(path.relative_to(output))
            saved.parent.mkdir(exist_ok=True)
            saved.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        records.append(record)
        print(f'[{index}/{len(assets)}] {cue}: {len(record["streams"])} streams verified', flush=True)
    report = {'schemaVersion': 1, 'identity': {k: source[k] for k in ('region', 'channel', 'contentReleaseId')},
              'catalogSha256': CATALOG_SHA256, 'complete': len(records) == len(assets), 'files': records}
    path = output / ('bgm-audio-report.json' if report['complete'] else 'sample-report.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(path, flush=True)


if __name__ == '__main__':
    main()
