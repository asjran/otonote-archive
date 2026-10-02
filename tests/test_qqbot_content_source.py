"""The bot follows the same immutable content pointer as the website."""
import hashlib
import json

import httpx
import pytest

from test_qqbot import bundle, reply_text
from backend.qqbot.query import Queries
from backend.qqbot.website import WebsiteCache


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


@pytest.fixture
def source(bundle):
    release = 'global-prod-remote-1-0-0-105-test'
    documents = {name: json.loads((bundle/name).read_text()) for name in
                 ('catalog.json', 'card-detail-projections.json', 'global-systems.json')}
    catalog = documents['catalog.json']
    catalog['release']['id'] = release
    catalog['projectionContext']['contentReleaseId'] = release
    for asset in catalog['assets']:
        asset['sourceReleaseId'] = release
    systems = documents['global-systems.json']
    systems['sourceReleaseId'] = release
    systems['gachaPools'][0]['endAt'] = '2026/10/8 23:59:59'
    documents['game-database.json'] = {'sourceReleaseId': release, 'skills': []}
    old = json.loads((bundle/'manifest.json').read_text())
    art = (bundle/old['images']['asset-test']).read_bytes()
    root = '/content/releases/' + 'a'*24 + '/'
    documents['media-index.json'] = {'contentReleaseId': release, 'records': [{
        'id': 'asset-test', 'publicPolicy': 'public', 'tiers': {'webPreview': {
            'state': 'available', 'variants': [{'url': root+'public/art.png',
            'sha256': hashlib.sha256(art).hexdigest(), 'width': 200, 'byteSize': len(art)}]}}}]}
    routes = {root+'public/art.png': art}
    state = {'offline': False, 'requests': []}

    def publish():
        records = {}
        for name, doc in documents.items():
            raw = encoded(doc)
            routes[root+'zh-CN/'+name] = raw
            records['projection/'+name] = {'path': 'zh-CN/'+name,
                'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        manifest = {'schemaVersion': 1, 'contentReleaseId': release, 'root': root,
                    'locales': {'zh-CN': {'files': records}}}
        raw = encoded(manifest)
        routes[root+'manifest.json'] = raw
        routes['/content/current.json'] = encoded({'schemaVersion': 1, 'contentReleaseId': release,
            'manifest': root+'manifest.json', 'sha256': hashlib.sha256(raw).hexdigest()})
    publish()

    def request(req):
        state['requests'].append(req.url.path)
        if state['offline']:
            raise httpx.ConnectError('offline', request=req)
        return httpx.Response(200, content=routes[req.url.path])

    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        yield documents, routes, state, publish, client, root


def cache(tmp_path, source):
    return WebsiteCache(tmp_path/'cache', 'https://site.test/content/current.json', http=source[4])


def test_live_content_dates_and_demand_loaded_verified_images(tmp_path, source):
    c = cache(tmp_path, source)
    assert c.refresh()
    assert c.content.release_id == 'global-prod-remote-1-0-0-105-test'
    assert c.content.snapshot == '1.0.0.105'
    assert source[5]+'public/art.png' not in source[2]['requests']
    reply = Queries(c.content).query('查卡池 1')
    assert '2026/10/8 23:59:59' in reply_text(reply)
    assert reply.image.is_file()
    before = c.requests
    Queries(c.content).query('查卡池 1')
    assert c.requests == before
    assert not c.refresh() and c.requests == before+1 and not c.stale


def test_update_failure_recovery_and_offline_restart(tmp_path, source):
    c = cache(tmp_path, source)
    assert c.refresh()
    old = c.content
    documents, routes, state, publish, _, root = source
    documents['global-systems.json']['gachaPools'][0]['endAt'] = '2026/10/9 23:59:59'
    publish()
    valid = routes[root+'zh-CN/global-systems.json']
    routes[root+'zh-CN/global-systems.json'] = b'{}'
    assert not c.refresh() and c.content is old and c.stale
    routes[root+'zh-CN/global-systems.json'] = valid
    before = len(state['requests'])
    assert c.refresh()
    assert state['requests'][before:] == ['/content/current.json', root+'manifest.json', root+'zh-CN/global-systems.json']
    assert '2026/10/9' in reply_text(Queries(c.content).query('查卡池 1'))
    state['offline'] = True
    restarted = cache(tmp_path, source)
    assert restarted.content.release_id == c.content.release_id
    assert not restarted.refresh() and restarted.stale
    assert '2026/10/9' in reply_text(Queries(restarted.content).query('查卡池 1'))


def test_website_rollback_and_restart_use_same_source_revision(tmp_path, source):
    c = cache(tmp_path, source)
    assert c.refresh()
    original_pointer = source[1]['/content/current.json']
    original_manifest = source[1][source[5]+'manifest.json']
    original_revision = c.source_revision
    source[0]['global-systems.json']['gachaPools'][0]['endAt'] = '2026/10/9 23:59:59'
    source[3]()
    assert c.refresh()
    source[1]['/content/current.json'] = original_pointer
    source[1][source[5]+'manifest.json'] = original_manifest
    assert c.refresh()
    assert c.source_revision == original_revision
    assert '2026/10/8' in reply_text(Queries(c.content).query('查卡池 1'))
    restarted = cache(tmp_path, source)
    assert restarted.source_revision == original_revision
    before = restarted.requests
    assert not restarted.refresh() and restarted.requests == before+1 and not restarted.stale


@pytest.mark.parametrize('defect', ['identity', 'asset_origin', 'file_path', 'manifest_digest'])
def test_invalid_content_does_not_replace_cache(tmp_path, source, defect):
    c = cache(tmp_path, source)
    assert c.refresh()
    old = c.content
    docs, routes, _, publish, _, root = source
    if defect == 'identity':
        docs['global-systems.json']['sourceReleaseId'] = 'wrong'
    if defect == 'asset_origin':
        docs['media-index.json']['records'][0]['tiers']['webPreview']['variants'][0]['url'] = 'https://other.test/art.png'
    publish()
    if defect in ('file_path', 'manifest_digest'):
        manifest = json.loads(routes[root+'manifest.json'])
        manifest['locales']['zh-CN']['files']['projection/catalog.json']['path'] = '../../catalog.json'
        routes[root+'manifest.json'] = encoded(manifest)
        pointer = json.loads(routes['/content/current.json'])
        pointer['sha256'] = hashlib.sha256(routes[root+'manifest.json']).hexdigest() if defect == 'file_path' else 'b'*64
        routes['/content/current.json'] = encoded(pointer)
    assert not c.refresh() and c.content is old and c.stale
