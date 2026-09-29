from __future__ import annotations
import hashlib
import json
from pathlib import Path
import httpx
import pytest
from test_qqbot import bundle
from backend.qqbot.website import WebsiteCache
from backend.qqbot.content import Content
from backend.qqbot.query import Queries
from backend.qqbot.render import Renderer
from backend.qqbot.app import Delivery


@pytest.fixture
def website(bundle):
    m=json.loads((bundle/'manifest.json').read_text())
    routes={};files=dict(m['files'])
    original={k:v for k,v in files.items() if not k.startswith('images/')}
    database={'sourceReleaseId':m['releaseId'],'skills':[]}
    raw=json.dumps(database).encode();original['game-database.json']=hashlib.sha256(raw).hexdigest()
    routes['/db']=raw
    urls={}
    for name in original:
        if name=='game-database.json':urls[name]='/db';continue
        routes['/'+name]=(bundle/name).read_bytes();urls[name]='/'+name
    asset=m['images']['asset-test'];raw=(bundle/asset).read_bytes();digest=hashlib.sha256(raw).hexdigest();routes['/art']=raw
    manifest={**m,'schemaVersion':2,'images':{},'files':original,'fileUrls':urls,'remoteAssets':{'asset-test':{'sha256':digest,'suffix':'.png','url':'/art'}}}
    state={'etag':'"v1"','offline':False,'requests':[]}
    def publish():
        raw=json.dumps(manifest).encode();revision=hashlib.sha256(raw).hexdigest();routes['/manifest']=raw
        routes['/current']=json.dumps({'revision':revision,'manifest':'/manifest'}).encode()
        state['etag']='"'+revision+'"'
    publish()
    def request(req):
        state['requests'].append(req.url.path)
        if state['offline']:raise httpx.ConnectError('offline',request=req)
        if req.url.path=='/current' and req.headers.get('If-None-Match')==state['etag']:return httpx.Response(304)
        return httpx.Response(200,content=routes[req.url.path],headers={'ETag':state['etag']})
    client=httpx.Client(transport=httpx.MockTransport(request))
    yield manifest,routes,state,publish,client
    client.close()


def cache(tmp_path,website):
    return WebsiteCache(tmp_path/'cache','https://site.test/current',http=website[-1])


def test_cached_queries_never_request_site_and_304_is_single_request(tmp_path,website):
    c=cache(tmp_path,website);assert c.refresh()
    assert len(website[2]['requests'])==6
    q=Queries(c.content);r=Renderer(c.content.snapshot)
    r.render(q.query('查角色卡 1'));n=c.requests
    for _ in range(3):r.render(q.query('查角色卡 1'))
    assert c.requests==n
    assert not c.refresh() and c.requests==n+1 and not c.stale


def test_offline_restart_keeps_verified_data_and_art(tmp_path,website):
    c=cache(tmp_path,website);c.refresh();path=c.content.image('asset-test');assert path.is_file()
    website[2]['offline']=True
    restarted=cache(tmp_path,website);assert restarted.content is not None
    assert not restarted.refresh() and restarted.stale
    before=restarted.requests;assert restarted.content.image('asset-test').is_file();assert restarted.requests==before


def test_bad_update_preserves_active_snapshot_then_fetches_only_changed_json(tmp_path,website):
    c=cache(tmp_path,website);c.refresh();old=c.content
    m,routes,state,publish,_=website
    routes['/db']=json.dumps({'sourceReleaseId':m['releaseId'],'skills':[{'id':'skill-new'}]}).encode()
    m['files']['game-database.json']='a'*64;publish()
    assert not c.refresh() and c.content is old and c.stale
    m['files']['game-database.json']=hashlib.sha256(routes['/db']).hexdigest();publish()
    before=len(state['requests']);assert c.refresh()
    assert state['requests'][before:]==['/current','/manifest','/db']
    assert 'skill-new' in c.content.skills


def test_asset_digest_and_origin_checks(tmp_path,website):
    c=cache(tmp_path,website);c.refresh()
    website[1]['/art']=b'bad-image'
    assert c.content.image('asset-test') is None
    before=c.requests;assert c.content.image('asset-test') is None;assert c.requests==before
    c.content.manifest['remoteAssets']['asset-test']['url']='https://untrusted.test/image'
    c.failed_assets.clear()
    assert c.content.image('asset-test') is None


def test_corrupt_cached_asset_is_refetched(tmp_path,website):
    c=cache(tmp_path,website);c.refresh();p=c.content.image('asset-test');p.write_bytes(b'corrupt')
    n=c.requests;assert c.content.image('asset-test').read_bytes()==website[1]['/art'];assert c.requests==n+1


def test_cold_offline_returns_image_and_recovers(tmp_path,website):
    website[2]['offline']=True;c=cache(tmp_path,website);assert not c.refresh() and c.content is None
    delivery=Delivery(None,Renderer('暂不可用'),None,None,None,'https://bot.test',c)
    assert delivery.prepare('查角色卡 1')[0].startswith(b'\x89PNG')
    website[2]['offline']=False;assert c.refresh()
    assert delivery.prepare('查角色卡 1')[0].startswith(b'\x89PNG')


def test_cross_origin_pointer_does_not_issue_request(tmp_path,website):
    website[1]['/current']=json.dumps({'revision':'a'*64,'manifest':'https://untrusted.test/manifest'}).encode()
    c=cache(tmp_path,website);assert not c.refresh() and c.content is None
    assert website[2]['requests']==['/current']


def test_source_change_does_not_reuse_other_origin_snapshot(tmp_path,website):
    c=cache(tmp_path,website);c.refresh()
    other=WebsiteCache(c.root,'https://other.test/current',http=website[-1])
    assert other.content is None


def test_joined_templates_preserve_kind_specific_fields(bundle):
    c=Content(bundle)
    c.catalog['cardTaxonomy']={'attributes':[{'code':5,'names':{'zh-CN':'紫苑'},'iconAssetId':'asset-test'}],
                              'rarities':[{'code':4,'label':'SSR','iconAssetId':'asset-test'}]}
    c.characters['character-1']['profile']={'voiceActor':'CV. 测试','height':'155cm','school':'学校'}
    q=Queries(c)
    card=q.query('查角色卡 1');assert card.layout=='memberCards'
    assert card.visual['rarity']['label']=='SSR' and card.visual['attribute']['label']=='紫苑'
    assert card.visual['rarity']['image'].is_file()
    character=q.query('查角色 1');assert character.visual['profile']['height']=='155cm'
    song=q.query('查歌曲 1');assert song.visual['charts'][0]['fullComboStatus']=='conflict'
    gacha=q.query('查卡池 1');assert len(gacha.visual['pickups'])==2
    assert all(x['image'].is_file() for x in gacha.visual['pickups'])


def test_many_pickups_paginate_without_discarding_cards(bundle):
    c=Content(bundle);pool=c.systems['gachaPools'][0];pool['pickupMemberCardIds']=[1,2]*7
    reply=Queries(c).query('查卡池 1');assert len(reply.visual['pickups'])==14
    images=Renderer(c.snapshot).render(reply);assert 2<=len(images)<=4
