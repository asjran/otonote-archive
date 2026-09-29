"""Release-bound supplementary inputs shared by all website renderers."""
from pathlib import Path
import json
from tools.release_preflight import digest, PreflightError


def read_supplemental(source, root):
    binding = source.get('supplementalInputs')
    if not binding: return None
    directory = (root / binding['root']).resolve()
    if root.resolve() not in directory.parents: raise PreflightError('supplemental inputs escape repository')
    manifest = directory / 'manifest.json'
    if digest(manifest) != binding['sha256']: raise PreflightError('supplemental manifest mismatch')
    value = json.loads(manifest.read_text())
    if value.get('schemaVersion') != 1 or value.get('contentReleaseId') != source['contentReleaseId']:
        raise PreflightError('supplemental release mismatch')
    expected = value['files']
    actual = {str(p.relative_to(directory)) for group in ('public','data') for p in (directory / group).rglob('*') if p.is_file() and p.name != '.DS_Store'}
    if actual != set(expected): raise PreflightError('unlisted or missing supplemental file')
    for name, sha in expected.items():
        path = directory / name
        if directory not in path.resolve().parents or path.is_symlink() or digest(path) != sha:
            raise PreflightError('supplemental file integrity mismatch: ' + name)
    return directory
