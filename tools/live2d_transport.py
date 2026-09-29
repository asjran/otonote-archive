"""Add a byte-preserving JSON transport bundle to an unpublished content tree."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def bundle_model(folder: Path):
    manifest_path = folder / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    entries = [r for r in manifest['resources'] if r['file'].endswith('.json')]
    if len(entries) < 2:
        return
    files = {}
    for entry in entries:
        name = entry['file']
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or name in files:
            raise ValueError('unsafe Live2D bundle entry')
        path = folder / name
        if path.is_symlink():
            raise ValueError('linked Live2D bundle entry')
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Live2D bundle source checksum mismatch')
        # Store original text, including whitespace: client hashes and ZIP bytes stay identical.
        files[name] = data.decode('utf-8')
        json.loads(files[name])
    payload = (json.dumps({'schemaVersion': 1, 'files': files}, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    digest = hashlib.sha256(payload).hexdigest()
    filename = f'json-bundle-{digest[:24]}.json'
    if filename in {r['file'] for r in manifest['resources']}:
        raise ValueError('reserved Live2D bundle filename')
    target = folder / filename
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError('Live2D bundle collision')
    else:
        target.write_bytes(payload)
    manifest['jsonBundle'] = {'file': filename, 'bytes': len(payload), 'sha256': digest,
                              'files': list(files)}
    # Publication copies use hard links. Replace the manifest inode; never alter the sealed source.
    temporary = folder / '.manifest.transport.json'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + '\n')
    os.replace(temporary, manifest_path)


def bundle_live2d_tree(root: Path):
    for manifest in sorted(root.rglob('manifest.json')):
        bundle_model(manifest.parent)
