"""Bound updater-owned completed builds while keeping current and previous releases."""
from pathlib import Path
import re
import shutil
from tools.global_remote_sync import read_json


def history(previous, result):
    kept = [result['buildDirectory']]
    for item in ([previous['buildDirectory']] + previous.get('retainedBuilds', [])) if previous else []:
        if item not in kept: kept.append(item)
    return kept[:2]


def cleanup(workspace, publication_root, retained):
    workspace, root = Path(workspace).resolve(), Path(publication_root).resolve()
    protected = {(root / name).resolve() for name in ('current', 'previous') if (root / name).is_symlink()}
    removed = []
    # Only directories bearing our completed-publication marker are managed.
    for item in (root / 'releases').glob('auto-*'):
        if item.is_symlink() or item.resolve() in protected or not (item / '.update-release.json').is_file(): continue
        marker = read_json(item / '.update-release.json')
        if item.name != 'auto-' + marker.get('identity', '')[:20]: continue
        shutil.rmtree(item); removed.append(str(item))
    keep = {Path(p).resolve() for p in retained}
    for item in (workspace / 'builds').iterdir():
        if item.is_symlink() or item.resolve() in keep or not re.fullmatch(r'[a-f0-9]{20}(?:-[a-f0-9]{8})?', item.name): continue
        if not (item / 'package/bundle.json').is_file() and not (item / 'content-publication.json').is_file(): continue
        shutil.rmtree(item); removed.append(str(item))
    sync = workspace / 'sync-complete'
    protected_inputs = set()
    if (sync / 'state.json').is_file():
        state = read_json(sync / 'state.json')
        protected_inputs.update(Path(state[k]).resolve() for k in ('inputPlan', 'snapshot'))
    for build in keep:
        binding = build / 'workflow-input.json'
        if binding.is_file(): protected_inputs.add(Path(read_json(binding)['inputPlan']).resolve())
    if sync.is_dir():
        for item in sync.iterdir():
            if (not item.is_dir() or item.is_symlink()
                    or not re.fullmatch(r'[0-9.]+-[a-f0-9]{8}-[a-f0-9]{8}-complete-v[0-9]+-[a-f0-9]{8}', item.name)
                    or not (item / 'inputs/release-inputs.json').is_file()): continue
            if any(item.resolve() == p or item.resolve() in p.parents for p in protected_inputs): continue
            shutil.rmtree(item); removed.append(str(item))
    return {'removed': removed, 'retainedBuilds': list(retained)}
