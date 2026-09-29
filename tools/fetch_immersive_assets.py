"""Fetch only the 39 catalogued home scenes, retaining the original capture binding."""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.global_remote_sync import acquire, file_hash, remote_path, write_json
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.adapters.global_public import GlobalPublicClient
from tools.prepare_immersive_catalog import CAPTURE, MASTER, CATALOG_SHA256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'input/global/remote-immersive/2026-09-27-catalog-39b5d81f')
    args = parser.parse_args()
    catalog_path = CAPTURE / 'RemoteCatalog/catalog_main.bin'
    if file_hash(catalog_path) != CATALOG_SHA256: raise ValueError('Capture catalog changed')
    locations = {x.primary_key: x for x in CatalogAdapter().parse(catalog_path).locations}
    spots = json.loads((MASTER / 'MasterHomeSpot.json').read_text())['_allData']
    names = {d for spot in spots for key in ('_backgroundAssetPath', '_situationAssetPath') for d in locations[spot[key]].dependencies if d.startswith('spot_')}
    capture = {p.name.split('_')[0]: p for p in (CAPTURE / 'EncryptedBundles').glob('*.bundle')}
    recorded = {x['path']: x for x in json.loads((CAPTURE / 'capture.json').read_text())['files']}
    reused, missing = [], []
    for name in sorted(names):
        local = capture.get(name[:-7].rsplit('_', 1)[-1])
        if local:
            actual = file_hash(local)
            if actual != recorded[str(local.relative_to(CAPTURE))]['sha256']: raise ValueError('Capture bytes changed')
            reused.append({'bundle': name, 'path': str(local.relative_to(ROOT)), 'sha256': actual, 'source': 'device-capture'})
        else: missing.append(locations[name])
    size = sum(x.expected_size for x in missing)
    if size > 512_000_000: raise ValueError('Scoped download exceeds 512 MB budget')
    print(json.dumps({'scenes': len(spots), 'bundles': len(names), 'cached': len(reused), 'missing': len(missing), 'downloadBytes': size}), flush=True)
    if not args.download: return
    observation = GlobalPublicClient().discover()
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / 'observation.json', observation)
    rows = list(reused)
    def fetch(location):
        # Some Addressables names leave no room for the receipt suffix on macOS.
        filename = location.primary_key if len(location.primary_key) < 210 else location.primary_key[:-7].rsplit('_', 1)[-1] + '.bundle'
        receipt = acquire(observation['cdnRoot'] + remote_path(location.internal_id), args.output / 'bundles' / filename, location.expected_size)
        return {'bundle': location.primary_key, 'path': str(Path(receipt['path']).relative_to(ROOT)), 'sha256': receipt['sha256'], 'source': 'cdn', 'catalogHash': location.expected_hash}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch, location): location for location in missing}
        try:
            for count, future in enumerate(as_completed(jobs), 1):
                rows.append(future.result())
                if count % 25 == 0 or count == len(missing): print(f'Fetched {count}/{len(missing)} bundles', flush=True)
        except BaseException:
            for job in jobs: job.cancel()
            raise
    write_json(args.output / 'manifest.json', {'schemaVersion': 1, 'catalogSha256': CATALOG_SHA256, 'masterSha256': file_hash(MASTER / 'MasterHomeSpot.json'), 'sceneCount': len(spots), 'files': sorted(rows, key=lambda x: x['bundle'])})
    print('All scoped scene dependencies acquired and receipted.', flush=True)


if __name__ == '__main__': main()
