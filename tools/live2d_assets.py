"""Verify the complete Live2D resource closure before static publication."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify_live2d_assets(catalog, public_root: Path, release: str):
    if catalog['releaseId'] != release:
        raise ValueError('Live2D catalog belongs to another release')
    models = resources = total = 0
    for model in catalog['models']:
        if model['state'] != 'available':
            continue
        prefix = f'/live2d/{release}/'
        root = model['root']
        if not root.startswith(prefix) or '..' in PurePosixPath(root).parts:
            raise ValueError('unsafe Live2D model path')
        folder = public_root / root.lstrip('/')
        manifest = json.loads((folder / 'manifest.json').read_text())
        names = set()
        model_bytes = 0
        for resource in manifest['resources']:
            name = resource['file']
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or name in names:
                raise ValueError('unsafe or duplicate Live2D resource')
            names.add(name)
            path = folder / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != resource['bytes']:
                raise ValueError(f'Live2D resource missing / size mismatch: {name}')
            if hashlib.sha256(path.read_bytes()).hexdigest() != resource['sha256']:
                raise ValueError(f'Live2D resource checksum mismatch: {name}')
            model_bytes += resource['bytes']
        settings = json.loads((folder / manifest['model']).read_text())
        refs = settings['FileReferences']
        required = [manifest['model'], refs['Moc'], *refs['Textures']]
        required += [refs[k] for k in ('Physics', 'Pose') if k in refs]
        required += [e['File'] for e in refs.get('Expressions', [])]
        required += [m['File'] for group in refs.get('Motions', {}).values() for m in group]
        if not set(required).issubset(names):
            raise ValueError('Live2D settings reference an unlisted resource')
        if model_bytes != manifest['totalBytes'] or model_bytes != model['bytes']:
            raise ValueError('Live2D resource totals mismatch')
        if manifest['model'] not in names:
            raise ValueError('Live2D settings missing from manifest')
        models += 1; resources += len(names); total += model_bytes
    return {'models': models, 'resources': resources, 'bytes': total}
