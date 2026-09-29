"""Functional, image-only delivery, persistence and official-protocol contracts."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.qqbot.app import create_app
from backend.qqbot.config import Config
from backend.qqbot.content import Content, ContentError
from backend.qqbot.query import Queries, Reply, Section
from backend.qqbot.render import Renderer
from backend.qqbot.store import Images, Outbox
from backend.qqbot.transport import QQClient, QQError, challenge, key_from_secret, verify
from tools.qqbot_bundle import build

RELEASE = "global-prod-20260924-fixture"
SECRET = "test-secret"


@pytest.fixture
def bundle(tmp_path):
    site = tmp_path / "site"
    data = site / "global/zh-CN/data"
    data.mkdir(parents=True)
    (site / "media").mkdir()
    Image.new("RGB", (200, 100), "#3388BB").save(site / "media/fixture.png")
    characters = [{"id": "character-1", "masterId": 1, "displayName": "高松灯", "aliases": ["燈", "Tomori"],
                   "bandId": "band-1", "role": "Vo.", "birthday": {"month": 11, "day": 22},
                   "memberCardIds": ["member-card-1"], "featuredSupportCardIds": ["support-card-1"], "profileAssetId": "asset-test"}]
    cards = [{"id": f"member-card-{i}", "masterId": i, "displayName": f"高松灯｜测试卡{i}", "characterId": "character-1",
              "rarity": 4, "attributeCode": 5, "performancePowerMax": 100, "technicPowerMax": 200,
              "visualPowerMax": 300, "primaryAssetId": "asset-test"} for i in range(1, 9)]
    support = {"id": "support-card-1", "masterId": 1, "displayName": "好想成为人类", "featuredCharacterIds": ["character-1"],
               "rarity": 4, "attributeCode": 5, "primaryAssetId": "asset-test"}
    song = {"id": "music-1", "masterId": 1, "title": "迷星叫", "bandLabels": ["MyGO!!!!!"], "vocalistLabels": ["高松灯"],
            "vocalCharacterIds": ["character-1"], "bandIds": ["band-1"], "bpm": {"min": 190, "max": 190}, "jacketAssetId": "asset-test"}
    asset = {"id": "asset-test", "publicPolicy": "public", "sourceReleaseId": RELEASE,
             "previewUrl": "/media/fixture.png", "containerPath": "Assets/AddressableResources/Gacha/Banner/gacha1.png"}
    catalog = {"release": {"id": RELEASE, "region": "global", "channel": "production"},
               "projectionContext": {"contentReleaseId": RELEASE, "region": "global", "channel": "production", "locale": "zh-CN"},
               "characters": characters, "bands": [{"id": "band-1", "displayName": "MyGO!!!!!", "mainColor": "#3388BB"}],
               "memberCards": cards, "supportCards": [support], "musicTracks": [song], "assets": [asset],
               "musicCharts": [{"id": "chart-1", "trackId": "music-1", "difficulty": "expert", "level": 25,
                                "fullComboCount": 766, "masterFullComboCount": 767, "fullComboStatus": "conflict"}]}
    systems = {"sourceReleaseId": RELEASE, "gachaPools": [{"id": 1, "name": "MyGO开服招募", "startAt": "2026/09/01 00:00:00",
                "endAt": "2026/09/28 11:59:59", "pickupMemberCardIds": [1, 2], "bannerAssetName": "Gacha/Banner/gacha1"}], "studioUnits": []}
    details = {"memberCards": [{"cardId": "member-card-1", "skillSummaries": [{"name": "得分UP", "level": 5, "summary": "5秒内得分提升70%", "interpretationStatus": "partial"}]}],
               "supportCards": [{"cardId": "support-card-1", "skillSummaries": [{"name": "留影技能", "level": 5, "summary": "测试技能", "interpretationStatus": "identified"}]}]}
    for name, value in (("catalog.json", catalog), ("global-systems.json", systems), ("card-detail-projections.json", details)):
        (data / name).write_text(json.dumps(value, ensure_ascii=False))
    output = tmp_path / "bundle"
    build(site, output)
    return output


@pytest.fixture
def content(bundle):
    return Content(bundle)


def reply_text(reply):
    return "\n".join([reply.title, reply.subtitle, reply.notice] + [s.title + "\n" + "\n".join(s.lines) for s in reply.sections])


class TestFiveFeatures:
    def test_card_id_and_partial_skill(self, content):
        reply = Queries(content).query("查角色卡 1")
        assert "测试卡1" in reply.title
        assert "100 / 技巧 200 / 视觉 300" in reply_text(reply)
        assert "尚未完整解析" in reply_text(reply)
        assert reply.image.is_file()

    def test_card_alias_and_pagination(self, content):
        q = Queries(content)
        assert "8 项" in q.query("查角色卡 Tomori").title
        second = reply_text(q.query("查角色卡 燈 第2页"))
        assert "测试卡7" in second and "测试卡1" not in second

    def test_snap_name_and_character_alias(self, content):
        q = Queries(content)
        assert q.query("查留影 好想成为人类").title == "好想成为人类"
        assert "留影技能" in reply_text(q.query("查留影 燈"))

    def test_song_bpm_and_count_conflict(self, content):
        reply = Queries(content).query("查歌曲 迷星叫")
        text = reply_text(reply)
        assert "190 — 190" in text and "EXPERT  Lv.25" in text
        assert "766（重建值；Master 767）" in text and "待游戏内核验" in text

    def test_gacha_up_links_and_raw_time(self, content):
        reply = Queries(content).query("查卡池 Tomori")
        text = reply_text(reply)
        assert "2026/09/28 11:59:59" in text and "时区未核验" in text
        assert "查角色卡 member-card-2" in text
        assert reply.image.is_file()

    def test_gacha_no_up_no_end(self, content):
        item = content.systems["gachaPools"][0]
        item.update(pickupMemberCardIds=[], endAt=None)
        text = reply_text(Queries(content).query("查卡池 1"))
        assert "没有标记 UP" in text and "结束：未配置" in text

    def test_character_alias_birthday_and_band(self, content):
        text = reply_text(Queries(content).query("查角色 燈"))
        assert "高松灯" in text and "11 月 22 日" in text and "MyGO!!!!!" in text

    @pytest.mark.parametrize("command", ["查角色卡", "查留影", "查歌曲", "查卡池", "查角色"])
    def test_no_result(self, content, command):
        assert Queries(content).query(command + " 不存在的资料").title == "没有找到对应资料"

    @pytest.mark.parametrize("message", ["帮助", "/帮助", "<@!123> /帮助", ""])
    def test_help_variants(self, content, message):
        assert "五项查询" in reply_text(Queries(content).query(message))

    def test_blank_query_page(self, content):
        assert "测试卡7" in reply_text(Queries(content).query("查角色卡 第2页"))

    @pytest.mark.parametrize("page", [0, 999999])
    def test_page_out_of_range(self, content, page):
        assert Queries(content).query(f"查角色卡 第{page}页").kind == "分页提示"

    def test_empty_symbols_do_not_match_all(self, content):
        assert "没有找到" in Queries(content).query("查角色卡 !!!").title

    def test_unknown_and_long_input(self, content):
        q = Queries(content)
        assert q.query("无效指令").kind == "输入提示"
        assert q.query("查角色卡 " + "a" * 201).title == "指令过长"

    @pytest.mark.parametrize("command", ["查活动档线", "查活动排名", "查活动排期", "查录音室进度"])
    def test_future_capabilities_are_not_claimed_live(self, content, command):
        assert Queries(content).query(command).title == "这项查询尚未开放"

    def test_future_provider_extension(self, content):
        class Provider:
            def query(self, capability, keyword):
                assert capability == "events" and keyword == "测试"
                return Reply("活动排期", "配置排期", notice="配置来源与时间由 provider 提供")
        assert Queries(content, {"events": Provider()}).query("查活动排期 测试").title == "配置排期"


class TestBundleAndImages:
    def test_tampered_data_rejected(self, bundle):
        with (bundle / "catalog.json").open("a") as file:
            file.write(" ")
        with pytest.raises(ContentError, match="integrity"):
            Content(bundle)

    def test_cross_release_rejected_even_with_updated_hash(self, bundle):
        path = bundle / "global-systems.json"
        value = json.loads(path.read_text())
        value["sourceReleaseId"] = "wrong"
        path.write_text(json.dumps(value))
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(ContentError, match="one Global"):
            Content(bundle)

    def test_unsafe_bundle_path(self, bundle):
        path = bundle / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["../outside"] = "a" * 64
        path.write_text(json.dumps(manifest))
        with pytest.raises(ContentError):
            Content(bundle)

    def test_missing_font_fails_clearly(self, content):
        with pytest.raises(ValueError, match="font"):
            Renderer(content.snapshot, "/missing-font.ttf")

    def test_default_font_covers_chinese_and_song_note(self, content):
        renderer = Renderer(content.snapshot)
        for character in "高松燈♪★♡・🜁🜃":
            font = renderer.glyph_font(character, 26)
            missing = bytes(font.getmask(chr(0x10FFFF)))
            assert bytes(font.getmask(character)) != missing

    @pytest.mark.parametrize("command", ["查角色卡 1", "查留影 1", "查歌曲 1", "查卡池 1", "查角色 1", "帮助", "查角色卡 第2页", "查歌曲 不存在", "查活动排名"])
    def test_all_reply_types_are_png(self, content, command):
        images = Renderer(content.snapshot).render(Queries(content).query(command))
        assert 1 <= len(images) <= 4
        for image in images:
            with Image.open(io.BytesIO(image)) as png:
                assert png.format == "PNG" and png.width == 900 and 620 <= png.height <= 2500

    def test_missing_art_still_returns_image(self, content):
        reply = Queries(content).query("查角色卡 1")
        reply.image = Path("/missing.png")
        assert Renderer(content.snapshot).render(reply)[0].startswith(b"\x89PNG")

    def test_long_details_paginate_without_text_loss(self, content):
        renderer = Renderer(content.snapshot)
        reply = Reply("测试", "长资料", sections=[Section("技能", ["长文字" * 8 for _ in range(80)])])
        assert 2 <= len(renderer.render(reply)) <= 4
        assert "".join(renderer.wrap("中文LongText" * 50, 200, 26)) == "中文LongText" * 50

    def test_image_cache_reuses_content_and_cleans_expired(self, tmp_path):
        import os
        images = Images(tmp_path / "images")
        name = images.put(b"test")
        assert images.put(b"test") == name
        os.utime(images.root / name, (time.time() - 90000, time.time() - 90000))
        images.sweep()
        assert not (images.root / name).exists()


class TestOfficialSignature:
    def test_official_public_key_vector_and_raw_body_verification(self):
        key = key_from_secret(SECRET)
        assert list(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)) == [215, 195, 98, 254, 120, 174, 248, 31, 242, 50, 135, 180, 147, 98, 139, 93, 176, 42, 60, 79, 227, 11, 33, 94, 77, 25, 96, 155, 93, 118, 103, 58]
        body = b'{ "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}'
        signature = key.sign(b"1725442341" + body).hex()
        assert verify(SECRET, body, "1725442341", signature, now=1725442341)
        assert not verify(SECRET, body + b" ", "1725442341", signature, now=1725442341)
        assert not verify(SECRET, body, "1725442341", signature, now=1725442741)

    def test_inconsistent_published_signature_is_rejected(self):
        # The official page's displayed body/signature do not match. Do not normalize
        # the body or weaken verification to accommodate this documentation example.
        signature = "865ad13a61752ca65e26bde6676459cd36cf1be609375b37bd62af366e1dc25a8dc789ba7f14e017ada3d554c671a911bfdf075ba54835b23391d509579ed002"
        assert not verify(SECRET, b'{ "op": 0,"d": {}, "t": "GATEWAY_EVENT_NAME"}', "1725442341", signature, now=1725442341)

    def test_official_challenge_vector(self):
        expected = "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"
        assert challenge("DG5g3B4j9X2KOErG", "Arq0D5A61EgUu4OxUvOp", "1725442341")["signature"] == expected


def event(scene="groups", message_id="msg1", command="查角色卡 1"):
    author = {"member_openid": "sender"} if scene == "groups" else {"user_openid": "sender"}
    return {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE" if scene == "groups" else "C2C_MESSAGE_CREATE",
            "d": {"id": message_id, "content": command, "group_openid": "group", "author": author,
                  "timestamp": datetime.now(timezone.utc).isoformat()}}


def signed_post(client, payload, **overrides):
    body = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    headers = {"X-Bot-Appid": "123", "X-Signature-Timestamp": stamp,
               "X-Signature-Ed25519": key_from_secret(SECRET).sign(stamp.encode() + body).hex()}
    headers.update(overrides)
    return client.post("/qqbot/callback", content=body, headers=headers)


@pytest.fixture
def app_setup(bundle, tmp_path):
    requests = []
    def upstream(request):
        requests.append(request)
        if request.url.path.endswith("getAppAccessToken"):
            return httpx.Response(200, json={"access_token": "fixture-token", "expires_in": "7200"})
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"file_info": "fixture-file", "ttl": 300})
        return httpx.Response(200, json={"id": "reply-id"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    config = Config("123", SECRET, bundle, tmp_path / "state", "https://bot.example.com")
    app = create_app(config, http=http, run_worker=False)
    with TestClient(app) as client:
        yield app, client, requests
    asyncio.run(http.aclose())


class TestQQWebhook:
    def test_partial_image_delivery_retries_only_unsent_page(self, app_setup, monkeypatch):
        app, client, _ = app_setup
        delivery = app.state.delivery
        real_page = delivery.renderer.render(Reply("测试", "分页样张"))[0]
        monkeypatch.setattr(delivery.renderer, "render", lambda _: [real_page, real_page])
        sequences = []
        async def send(scene, target, message_id, seq, url):
            sequences.append(seq)
            if sequences == [1, 2]:
                raise QQError("http_429", retryable=True)
        monkeypatch.setattr(delivery.client, "send_image", send)
        signed_post(client, event())
        client.portal.call(delivery.once)
        row = delivery.outbox.db.execute("SELECT sent,state FROM jobs").fetchone()
        assert tuple(row) == (1, "pending")
        with delivery.outbox.db:
            delivery.outbox.db.execute("UPDATE jobs SET next_at=0")
        client.portal.call(delivery.once)
        assert sequences == [1, 2, 2]
        assert delivery.outbox.counts() == {"sent": 1}

    def test_permanent_failure_is_observable_without_text_fallback(self, app_setup, monkeypatch):
        app, client, requests = app_setup
        async def fail(*args):
            raise QQError("api_850018")
        monkeypatch.setattr(app.state.delivery.client, "send_image", fail)
        signed_post(client, event())
        client.portal.call(app.state.delivery.once)
        assert client.get("/health/ready").json()["delivery"] == {"failed": 1}
        assert not requests

    @pytest.mark.parametrize("scene", ["groups", "users"])
    def test_query_upload_and_send_image_only(self, app_setup, scene):
        app, client, requests = app_setup
        assert signed_post(client, event(scene)).json() == {"op": 12, "d": 0}
        assert client.portal.call(app.state.delivery.once)
        assert len(requests) == 3
        upload, reply = json.loads(requests[1].content), json.loads(requests[2].content)
        assert upload["file_type"] == 1 and upload["srv_send_msg"] is False
        assert f"/v2/{scene}/" in requests[1].url.path
        assert reply == {"msg_type": 7, "media": {"file_info": "fixture-file"}, "msg_id": "msg1", "msg_seq": 1}
        assert "content" not in reply
        image = client.get(upload["url"].removeprefix("https://bot.example.com"))
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert app.state.outbox.counts() == {"sent": 1}

    def test_duplicate_event_sent_once(self, app_setup):
        app, client, requests = app_setup
        payload = event()
        assert signed_post(client, payload).status_code == 200
        assert signed_post(client, payload).status_code == 200
        client.portal.call(app.state.delivery.once)
        assert not client.portal.call(app.state.delivery.once)
        assert len(requests) == 3

    def test_challenge_and_invalid_signature(self, app_setup):
        _, client, requests = app_setup
        result = client.post("/qqbot/callback", json={"op": 13, "d": {"plain_token": "test", "event_ts": "1725442341"}}, headers={"X-Bot-Appid": "123"})
        assert result.json() == challenge(SECRET, "test", "1725442341")
        assert signed_post(client, event(), **{"X-Signature-Ed25519": "00"}).status_code == 401
        assert signed_post(client, event(), **{"X-Bot-Appid": "other"}).status_code == 401
        assert not requests

    def test_signed_heartbeat_and_invalid_signed_challenge(self, app_setup):
        _, client, _ = app_setup
        assert signed_post(client, {"op": 1, "d": 42}).json() == {"op": 11, "d": 42}
        assert signed_post(client, {"op": 1, "d": "42"}).status_code == 400
        assert signed_post(client, {"op": 13, "d": {"plain_token": "test", "event_ts": "1725442341"}},
                           **{"X-Signature-Ed25519": "00"}).status_code == 401

    def test_invalid_body_and_missing_fields(self, app_setup):
        _, client, _ = app_setup
        assert client.post("/qqbot/callback", content=b"x" * 65537, headers={"X-Bot-Appid": "123"}).status_code == 413
        assert client.post("/qqbot/callback", json=[], headers={"X-Bot-Appid": "123"}).status_code == 400
        payload = event()
        del payload["d"]["timestamp"]
        assert signed_post(client, payload).status_code == 400

    def test_expired_message_and_unsubscribed_event_are_ignored(self, app_setup):
        app, client, requests = app_setup
        payload = event()
        payload["d"]["timestamp"] = "2020-01-01T00:00:00Z"
        assert signed_post(client, payload).status_code == 200
        assert signed_post(client, {"op": 0, "t": "FRIEND_ADD", "d": {}}).status_code == 200
        assert app.state.outbox.counts() == {} and not requests

    def test_queue_bound_and_rate_limit(self, app_setup):
        app, client, _ = app_setup
        app.state.outbox.limit = 1
        assert signed_post(client, event(message_id="a")).status_code == 200
        assert signed_post(client, event(message_id="b")).status_code == 503
        app.state.outbox.limit = 200
        for i in range(9):
            assert signed_post(client, event(message_id=str(i))).status_code == 200
        assert signed_post(client, event(message_id="limit")).status_code == 429

    def test_unknown_image_and_health(self, app_setup):
        app, client, _ = app_setup
        assert client.get("/qqbot/images/not-a-hash.png").status_code == 404
        assert client.get("/health/ready").json()["releaseId"] == RELEASE
        assert client.get("/docs").status_code == 404

    def test_query_failure_still_renders_an_image(self, app_setup, monkeypatch):
        app, client, requests = app_setup
        def broken(_):
            raise ValueError("private internal details")
        monkeypatch.setattr(app.state.delivery.queries, "query", broken)
        signed_post(client, event())
        client.portal.call(app.state.delivery.once)
        assert json.loads(requests[-1].content)["msg_type"] == 7


def job_payload(message_id="id"):
    return {"scene": "groups", "target": "group", "sender": "user", "message_id": message_id,
            "command": "帮助", "expires": time.time() + 200}


class TestDurableOutbox:
    def test_sent_event_dedup_survives_restart(self, tmp_path):
        path = tmp_path / "db"
        box = Outbox(path)
        payload = job_payload()
        box.enqueue(payload)
        box.finish(box.next()["key"])
        box.close()
        box = Outbox(path)
        assert box.enqueue(payload) == "duplicate"
        assert box.next() is None
        box.close()

    def test_pending_and_partial_progress_survive_restart(self, tmp_path):
        path = tmp_path / "outbox.sqlite3"
        first = Outbox(path)
        payload = job_payload()
        assert first.enqueue(payload) == "accepted"
        job = first.next()
        first.sent(job["key"], 1)
        first.close()
        second = Outbox(path)
        assert second.next()["sent"] == 1
        assert second.enqueue(payload) == "duplicate"
        second.finish(job["key"])
        assert second.next() is None
        assert second.db.execute("SELECT payload FROM jobs").fetchone()[0] == "{}"
        second.close()

    def test_retries_are_bounded_and_expire(self, tmp_path):
        box = Outbox(tmp_path / "db")
        box.enqueue(job_payload())
        for _ in range(3):
            job = box.next(now=time.time() + 10)
            box.fail(job, "http_429", True, 1)
        assert box.counts() == {"failed": 1}
        payload = job_payload("expired")
        payload["expires"] = time.time() - 1
        box.enqueue(payload)
        assert box.next() is None
        assert box.counts() == {"failed": 2}
        box.close()


class TestAPIClient:
    def test_expired_token_refresh_and_invalid_success_response(self):
        async def run():
            calls = []
            def handler(req):
                calls.append(req)
                return httpx.Response(200, json={"access_token": "new", "expires_in": 7200})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = QQClient("123", SECRET, http)
                client.token, client.expires = "old", 0
                assert await client.access_token() == "new"
                assert await client.access_token() == "new"
                assert len(calls) == 1
                with pytest.raises(QQError, match="missing_file_info"):
                    await client.send_image("users", "user", "id", 1, "https://example.com/a.png")
        asyncio.run(run())

    def test_token_cache_and_401_refresh(self):
        async def run():
            calls, tokens = [], []
            def handler(req):
                calls.append(req)
                if req.url.path.endswith("getAppAccessToken"):
                    tokens.append(1)
                    return httpx.Response(200, json={"access_token": f"token{len(tokens)}", "expires_in": 7200})
                if len(tokens) == 1:
                    return httpx.Response(401)
                return httpx.Response(200, json={"file_info": "ok"})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = QQClient("123", SECRET, http)
                assert (await client.api("/test", {}))["file_info"] == "ok"
                await client.api("/test", {})
                assert len(tokens) == 2 and calls[-1].headers["Authorization"] == "QQBot token2"
        asyncio.run(run())

    @pytest.mark.parametrize("status,body,retryable", [(200, {"code": 100016, "message": "secret leak"}, False),
                                                       (200, {"code": 100001}, True), (429, {}, True), (503, {}, True)])
    def test_business_and_http_errors(self, status, body, retryable):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))) as http:
                with pytest.raises(QQError) as failure:
                    await QQClient("123", SECRET, http).access_token()
                assert failure.value.retryable is retryable
                assert "secret leak" not in str(failure.value)
        asyncio.run(run())

    def test_upload_failure_never_sends_text(self):
        async def run():
            paths = []
            def handler(req):
                paths.append(req.url.path)
                if req.url.path.endswith("getAppAccessToken"):
                    return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
                return httpx.Response(200, json={"code": 850026})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                with pytest.raises(QQError):
                    await QQClient("123", SECRET, http).send_image("groups", "group", "msg", 1, "https://bot.example.com/a.png")
            assert not any(x.endswith("/messages") for x in paths)
        asyncio.run(run())
