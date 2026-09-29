"""Build an explicit analytics allowlist from a published static tree and export catalogs."""
import argparse
import json
from pathlib import Path


def build_catalog(root, live2d=None, scenes=None):
    root = Path(root).resolve()
    paths, resources = set(), set()
    for file in root.rglob('*'):
        if not file.is_file() or file.is_symlink() or any(p.startswith('.') for p in file.relative_to(root).parts):
            continue
        route = '/' + file.relative_to(root).as_posix()
        if file.suffix == '.html':
            paths.add(route[:-10] if route.endswith('index.html') else route)
            paths.add(route)
        else:
            resources.add(route)
    if live2d:
        data = json.loads(Path(live2d).read_text())
        resources.update('live2d:' + str(row['id']) for row in data['models'])
    if scenes:
        data = json.loads(Path(scenes).read_text())
        resources.update('scene:' + str(row['id']) + ':' + kind for row in data['scenes'] for kind in ('png','webm'))
    return {'schemaVersion': 1, 'paths': sorted(paths), 'resources': sorted(resources)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--site', required=True)
    p.add_argument('--live2d')
    p.add_argument('--scenes')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_catalog(args.site, args.live2d, args.scenes), ensure_ascii=False))
    print('Analytics catalog written:', output)


if __name__ == '__main__':
    main()
