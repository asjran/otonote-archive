"""Adapt the website's verified content release to the bot's bundle contract."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse

from .content import ContentError, DATA_FILES


def adapt_content(cache, pointer, manifest):
    release = pointer['contentReleaseId']
    root = manifest['root']
    if (pointer.get('schemaVersion') != 1 or manifest.get('schemaVersion') != 1
            or manifest.get('contentReleaseId') != release
            or not re.fullmatch(r'/content/releases/[a-f0-9]{24}/', root)
            or cache._url(pointer['manifest']) != cache._url(root+'manifest.json')):
        raise ContentError('invalid independent content identity')
    records = manifest['locales']['zh-CN']['files']
    files, urls = {}, {}
    for name in (*DATA_FILES, 'game-database.json', 'media-index.json'):
        record = records['projection/'+name]
        if record['path'] != 'zh-CN/'+name:
            raise ContentError('invalid content projection path')
        files[name], urls[name] = record['sha256'], root+record['path']
    media = json.loads(cache._blob(files['media-index.json'], urls['media-index.json']))
    if media.get('contentReleaseId') != release:
        raise ContentError('media index release mismatch')
    assets = {}
    for item in media['records']:
        if item.get('publicPolicy') != 'public':
            continue
        preview = item.get('tiers', {}).get('webPreview', {})
        variants = preview.get('variants', []) if preview.get('state') == 'available' else []
        if not variants:
            continue
        variant = max(variants, key=lambda v: v.get('width', 0))
        url = variant['url']
        cache._url(url)
        suffix = PurePosixPath(urlparse(url).path).suffix.lower()
        if (not url.startswith(root+'public/') or '..' in PurePosixPath(url).parts
                or suffix not in ('.png', '.webp', '.jpg', '.jpeg')):
            raise ContentError('invalid content asset URL')
        assets[item['id']] = {'sha256': variant['sha256'], 'suffix': suffix,
                              'url': url, 'bytes': variant['byteSize']}
    # Remote release IDs carry the game resource version, not a capture date.
    version = re.match(r'global-prod-remote-(\d+-\d+-\d+-\d+)-', release)
    date = re.match(r'global-prod-(\d{4})(\d{2})(\d{2})-', release)
    snapshot = version[1].replace('-', '.') if version else '-'.join(date.groups()) if date else '日期未提供'
    return {'schemaVersion': 2, 'releaseId': release, 'snapshotDate': snapshot,
            'files': {k: v for k, v in files.items() if k != 'media-index.json'},
            'fileUrls': {k: v for k, v in urls.items() if k != 'media-index.json'},
            'images': {}, 'remoteAssets': assets,
            'sourceRevision': pointer['sha256'],
            'sourceFiles': {'media-index.json': files['media-index.json']}}
