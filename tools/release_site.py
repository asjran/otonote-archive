"""Assemble an isolated static preview from a verified Global data candidate."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.release_preflight import PreflightError, digest
from tools.verify_site_product import verify
from tools.private_content_guard import verify_no_private_content
from tools.live2d_assets import verify_live2d_assets
from tools.immutable_files import link_or_copy, deduplicate_tree


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare_site_workspace(target: Path, *, root: Path = ROOT) -> Path:
    """Freeze rendering sources and keep Astro scratch files off the live site."""
    target.mkdir(parents=True)
    shutil.copytree(root / 'site/src', target / 'src')
    for name in ('astro.config.mjs', 'product-profile.mjs', 'package.json', 'tsconfig.json'):
        shutil.copy2(root / 'site' / name, target / name)
    (target.parent / 'config').mkdir()
    shutil.copy2(root / 'config/site-product.json', target.parent / 'config/site-product.json')
    for group in ('brand', 'images/filter-bands'):
        if (root / 'site/public' / group).is_dir():
            shutil.copytree(root / 'site/public' / group, target / 'public' / group)
    # These manifests are imported by the mission UI rather than projection
    # aliases. Snapshot their explicitly listed, digest-verified files too.
    for group in ('system-banners', 'mission-rewards', 'growth'):
        source = root / 'site/public' / group
        if not source.is_dir():
            continue
        raw = (source / 'manifest.json').read_bytes()
        entries = json.loads(raw)
        if isinstance(entries, dict): entries = entries['images']
        destination = target / 'public' / group
        destination.mkdir(parents=True)
        for entry in entries:
            name = entry['file']
            if Path(name).name != name or not name.endswith('.webp'):
                raise PreflightError('unsafe supplemental image path')
            shutil.copyfile(source / name, destination / name)
            if digest(destination / name) != entry['sha256']:
                raise PreflightError('supplemental image digest mismatch')
        (destination / 'manifest.json').write_bytes(raw)
    (target / 'node_modules').symlink_to((root / 'site/node_modules').resolve(), target_is_directory=True)
    return target


def rewrite_data(value, prefix, media):
    if isinstance(value, str):
        if value.startswith('/media/'):
            return media + value[len('/media/'):]
        if value.startswith('/data/'):
            return prefix + value.lstrip('/')
        return value
    if isinstance(value, list):
        return [rewrite_data(v, prefix, media) for v in value]
    if isinstance(value, dict):
        return {rewrite_data(k, prefix, media): rewrite_data(v, prefix, media) for k, v in value.items()}
    return value


def rewrite_html(text, prefix):
    def replace(match):
        url = match['url']
        if url.startswith(('//', '/global/', '/media/')):
            return match[0]
        return match['start'] + prefix + url.lstrip('/')
    return re.sub(r'(?P<start>\b(?:href|src|poster|data-src)=["\x27])(?P<url>/[^"\x27]*)', replace, text)


def build_site(candidate: Path, output: Path, ):
    candidate = candidate.resolve()
    if output.exists() or output.is_symlink():
        raise PreflightError('site output must be a new directory')
    output = output.resolve()
    protected = [candidate, *(ROOT / n for n in ('site', 'input', 'phone_dump', 'catalog', 'config', 'data'))]
    if any(output == p or p in output.parents or output in p.parents for p in protected):
        raise PreflightError('site output overlaps inputs')
    manifest = json.loads((candidate / 'candidate.json').read_text())
    if manifest.get('historicalReplay', False):
        raise PreflightError('historical candidates are no longer supported')
    entries = []
    regions = manifest['regions']
    if len(regions) != 1 or regions[0]['region'] != 'global':
        raise PreflightError('exactly one Global candidate is required')
    actual = {str(p.relative_to(candidate)) for p in candidate.rglob('*') if p.is_file() and p.name != '.DS_Store'}
    if actual != set(manifest['files']) | {'candidate.json'} or any(p.is_symlink() for p in candidate.rglob('*')):
        raise PreflightError('unlisted or linked candidate files')
    for name, sha in manifest['files'].items():
        path = (candidate / name).resolve()
        if candidate not in path.parents or digest(path) != sha:
            raise PreflightError(f'candidate integrity mismatch: {name}')
    for region in regions:
        if region['channel'] != 'production':
            raise PreflightError('candidate channel mismatch')
        if region['path'] != f"{region['region']}/{region['contentReleaseId']}" or not re.fullmatch('[A-Za-z0-9_-]+', region['contentReleaseId']):
            raise PreflightError('unsafe candidate region path')
        if not region['projections']:
            raise PreflightError('candidate region has no projections')
        for projection in region['projections']:
            locale = projection['locale']
            if locale not in {'zh-CN', 'en', 'ja', 'zh-TW'}:
                raise PreflightError('unsupported candidate locale')
            catalog = candidate / region['path'] / 'generated/releases' / region['contentReleaseId'] / locale / 'catalog.json'
            context = json.loads(catalog.read_text()).get('projectionContext', {})
            expected = {key: region[key] for key in ('region', 'channel', 'contentReleaseId')}
            expected['locale'] = locale
            if context != expected:
                raise PreflightError('catalog projection identity mismatch')
            entries.append({'region': region['region'], 'channel': region['channel'], 'locale': locale,
                            'contentReleaseId': region['contentReleaseId'],
                            'catalogPath': f"/{region['region']}/{locale}/data/catalog.json"})
    if len({(e['region'], e['locale']) for e in entries}) != len(entries):
        raise PreflightError('duplicate projection route')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        with tempfile.TemporaryDirectory(prefix='ournotes-site-') as temp:
            work = Path(temp)
            renderer = prepare_site_workspace(work / 'render-project/site')
            bound_region = candidate / regions[0]['path']
            supplemental_data = bound_region / 'supplemental-data'
            bound_public = bound_region / 'public'
            if supplemental_data.is_dir():
                for name in ('live2d-catalog.json', 'immersive-scenes.json', 'auto-stage-skin.json'):
                    shutil.copyfile(supplemental_data / name, renderer / 'src/data' / name)
                for group in ('system-banners', 'mission-rewards', 'growth'):
                    shutil.rmtree(renderer / 'public' / group, ignore_errors=True)
                    shutil.copytree(bound_public / group, renderer / 'public' / group)
            for region in regions:
                media = stage / 'media' / region['region'] / region['contentReleaseId']
                shutil.copytree(candidate / region['path'] / 'public/media', media, copy_function=link_or_copy)
            for entry in entries:
                region, release, locale = entry['region'], entry['contentReleaseId'], entry['locale']
                prefix = f'/{region}/{locale}/'
                source = candidate / region / release / 'generated/releases' / release / locale
                workspace = work / region / locale
                data, public = workspace / 'source', workspace / 'public'
                data.mkdir(parents=True)
                public.mkdir()
                for path in source.rglob('*.json'):
                    value = rewrite_data(json.loads(path.read_text()), prefix, f'/media/{region}/{release}/')
                    if path.name == 'media-index.json':
                        value['sha256'] = hashlib.sha256(json.dumps(value['records'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    write(data / path.relative_to(source), value)
                for shard_manifest in data.glob('database-shards/manifest.json'):
                    value = json.loads(shard_manifest.read_text())
                    for item in value['files']:
                        path = shard_manifest.parent / item['path']
                        item.update(sha256=digest(path), byteSize=path.stat().st_size)
                    value['totalBytes'] = sum(item['byteSize'] for item in value['files'])
                    write(shard_manifest, value)
                index = {'schemaVersion': 1, 'active': entry, 'projections': entries}
                write(data / 'release-index.json', index)
                shutil.copytree(data, public / 'data')
                for group in ('system-banners', 'mission-rewards', 'growth', 'brand', 'images/filter-bands'):
                    if (renderer / 'public' / group).is_dir():
                        shutil.copytree(renderer / 'public' / group, public / group)
                gallery_assets = candidate / next(r['path'] for r in regions if r['region'] == region) / 'public/gallery'
                if gallery_assets.is_dir():
                    shutil.copytree(gallery_assets, public / 'gallery')
                # The independently verified lobby is shared by the viewer and homepage preview.
                resource_public = bound_public if supplemental_data.is_dir() else ROOT / 'site/public'
                immersive_assets = resource_public / 'immersive'
                if immersive_assets.is_dir():
                    shutil.copytree(immersive_assets, public / 'immersive')
                if (resource_public / 'auto-stage').is_dir():
                    shutil.copytree(resource_public / 'auto-stage', public / 'auto-stage')
                # Live2D assets use a release-bound manifest and are requested only on click.
                live2d_catalog = json.loads((renderer / 'src/data/live2d-catalog.json').read_text())
                if live2d_catalog['releaseId'] != release:
                    raise PreflightError('Live2D catalog belongs to another release')
                verify_live2d_assets(live2d_catalog, resource_public, release)
                live2d_assets = resource_public / 'live2d' / release
                shutil.copytree(ROOT / 'site/public/vendor/live2d', public / 'vendor/live2d')
                # Versioned chart URLs remain valid within this projection.
                charts = data / 'music-charts'
                if charts.is_dir():
                    shutil.copytree(charts, public / 'data/releases' / release / locale / 'music-charts')
                shutil.copy2(ROOT / 'site/public/favicon.svg', public / 'favicon.svg')
                destination = stage / region / locale
                environment = {**os.environ, 'OURNOTES_SITE_PROFILE': 'v1', 'OURNOTES_SITE_BASE': prefix,
                               'OURNOTES_SITE_OUT_DIR': str(destination), 'OURNOTES_SITE_PUBLIC_DIR': str(public),
                               'OURNOTES_PROJECTION_DATA_ROOT': str(data), 'ASTRO_TELEMETRY_DISABLED': '1',
                               'OURNOTES_ASTRO_CACHE_DIR': str(workspace / 'astro-cache'),
                               'OURNOTES_VITE_CACHE_DIR': str(workspace / 'vite-cache'), 'PUBLIC_ANONTOKYO_ENABLED': '0'}
                subprocess.run(['npm', 'exec', '--', 'astro', 'build'], cwd=renderer, env=environment, check=True)
                if live2d_assets.is_dir():
                    shutil.copytree(live2d_assets, destination / 'live2d' / release, copy_function=link_or_copy)
                for html in destination.rglob('*.html'):
                    html.write_text(rewrite_html(html.read_text(), prefix))
                if locale == 'en':
                    subprocess.run(['node', str(ROOT / 'tools/localize_site_output.mjs'), str(destination), '--locale', locale], check=True)
            default = next((e for e in entries if e['locale'] == 'zh-CN'), entries[0])
            target = f"/{default['region']}/{default['locale']}/"
            (stage / 'index.html').write_text(f'<meta http-equiv="refresh" content="0;url={target}"><a href="{target}">OurNotes</a>')
        deduplicate_tree(stage, [(candidate / name, sha) for name, sha in manifest['files'].items()])
        report = verify(stage)
        if report['status'] != 'passed':
            raise PreflightError(f"site references failed: {report['failures'][:15]}")
        verify_no_private_content(stage)
        write(stage / 'site-candidate.json', {'schemaVersion': 1, 'historicalReplay': False,
               'publicationReady': False, 'projections': entries, 'validation': report,
               'limitations': ([] if supplemental_data.is_dir() else ['runtime_resources_not_bound']) + ['formal_gameplay_not_verified']})
        if output.exists():
            raise PreflightError('site output appeared during build')
        stage.rename(output)
        return report
    finally:
        if stage.exists():
            try:
                shutil.rmtree(stage)
            except OSError:
                print(f'Incomplete site files retained at {stage}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_site(args.candidate, args.output), indent=2))


if __name__ == '__main__':
    main()
