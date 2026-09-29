"""Read and export explicitly version-bound raw score payload snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.music_catalog import collect_score_payloads
from tools.release_preflight import PreflightError, check_environment, digest, load_plan


def safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or '\\' in value:
        raise PreflightError('invalid score path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'.', '..', ''} for part in value.split('/')):
        raise PreflightError('unsafe score path')
    return value


def identity(source: dict) -> dict:
    return {key: source[key] for key in ('region', 'channel', 'contentReleaseId')}


def read_score_inputs(source: dict, root: Path = ROOT) -> dict[str, bytes] | None:
    binding = source.get('scoreInputs')
    if binding is None:
        return None
    if not isinstance(binding, dict) or not isinstance(binding.get('index'), str) or not re.fullmatch('[a-f0-9]{64}', str(binding.get('sha256', ''))):
        raise PreflightError('invalid scoreInputs binding')
    index = root / binding['index']
    raw = index.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding['sha256']:
        raise PreflightError('score index digest mismatch')
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get('schemaVersion') != 1 or payload.get('identity') != identity(source):
        raise PreflightError('score input identity mismatch')
    records = payload.get('scores')
    if not isinstance(records, list) or not records:
        raise PreflightError('bound score input set must not be empty')
    scores = {}
    directory = index.parent.resolve()
    for record in records:
        if not isinstance(record, dict):
            raise PreflightError('invalid score record')
        logical = safe_path(record.get('logicalPath'))
        if not logical.endswith('.bytes') or logical in scores:
            raise PreflightError('invalid or duplicate logical score path')
        path = (directory / safe_path(record.get('file'))).resolve()
        if directory not in path.parents:
            raise PreflightError('score file escapes input directory')
        content = path.read_bytes()
        if not content or hashlib.sha256(content).hexdigest() != record.get('sha256') or len(content) != record.get('byteSize'):
            raise PreflightError(f'score payload digest/size mismatch: {logical}')
        scores[logical] = content
    return scores


def write_score_inputs(source: dict, scores: dict[str, bytes], output: Path) -> dict:
    if not scores:
        raise PreflightError('no extracted scores; input remains unbound')
    if output.exists() or output.is_symlink():
        raise PreflightError('score output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        records = []
        for logical, content in sorted(scores.items()):
            safe_path(logical)
            if not logical.endswith('.bytes') or not content:
                raise PreflightError('invalid raw score payload')
            sha = hashlib.sha256(content).hexdigest()
            name = f'payloads/{sha}.bytes'
            target = temporary / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(content)
            records.append({'logicalPath': logical, 'file': name, 'sha256': sha, 'byteSize': len(content)})
        (temporary / 'index.json').write_text(json.dumps({'schemaVersion': 1, 'identity': identity(source), 'scores': records}, indent=2) + '\n')
        if output.exists():
            raise PreflightError('score output appeared during export')
        temporary.rename(output)
        return {'index': str((output / 'index.json').resolve()), 'sha256': digest(output / 'index.json')}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'config/release-inputs.json')
    parser.add_argument('--environment', required=True)
    parser.add_argument('--bundle-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = next((entry for entry in load_plan(args.plan) if entry['id'] == args.environment), None)
    if source is None or check_environment(source)['status'] != 'passed':
        parser.error('selected input must pass preflight')
    extracted = source.get('extractedRoot')
    if not extracted or not (ROOT / extracted).is_dir():
        parser.error('explicit extractedRoot is required')
    protected = [args.plan.resolve(), args.bundle_root.resolve(), (ROOT / extracted).resolve(),
                 *(ROOT / name for name in ('site', 'input', 'phone_dump', 'catalog', 'config', 'data'))]
    output = args.output.resolve()
    if args.output.is_symlink() or any(output == p or p in output.parents or output in p.parents for p in protected):
        parser.error('score output overlaps protected inputs')
    manifest = json.loads((ROOT / source['assetManifest']).read_text())
    scores = collect_score_payloads(manifest, ROOT / extracted, args.bundle_root)
    if check_environment(source)['status'] != 'passed':
        parser.error('inputs changed while exporting scores')
    print(json.dumps(write_score_inputs(source, scores, output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
