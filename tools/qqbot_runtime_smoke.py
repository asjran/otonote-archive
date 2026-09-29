"""Run inside the runtime container with network disabled and a read-only bundle.

docker run --rm -i ... ournotes-qqbot:local-test python - < tools/qqbot_runtime_smoke.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from backend.qqbot.app import create_app
from backend.qqbot.config import Config
from backend.qqbot.render import Renderer, find_font
from backend.qqbot.transport import key_from_secret


def main():
    secret = "runtime-smoke-fixture-only"
    paths, replies = [], []
    def upstream(request):
        paths.append(request.url.path)
        if request.url.path.endswith("getAppAccessToken"):
            return httpx.Response(200, json={"access_token": "fixture-only", "expires_in": 7200})
        if request.url.path.endswith("/files"):
            body = json.loads(request.content)
            assert body["file_type"] == 1 and body["srv_send_msg"] is False
            return httpx.Response(200, json={"file_info": "fixture-only", "ttl": 300})
        body = json.loads(request.content)
        assert body["msg_type"] == 7 and "content" not in body
        replies.append(body)
        return httpx.Response(200, json={"id": "fixture-reply"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    config = Config("123", secret, Path("/content"), Path("/state"), "https://bot.example.com", data_url=os.environ.get("OURNOTES_QQ_DATA_URL"))
    app = create_app(config, http=http, run_worker=False)
    renderer = Renderer("2026-09-24")
    for char in "高松燈♪★♡・🜁🜃":
        renderer.glyph_font(char, 26)
    commands = ["查角色卡 51", "查留影 51", "查歌曲 100001", "查卡池 1", "查角色 1"]
    with TestClient(app) as client:
        first_scene_requests = None
        for scene in ("groups", "users"):
            for index, command in enumerate(commands):
                payload = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE" if scene == "groups" else "C2C_MESSAGE_CREATE",
                           "d": {"id": f"{scene}-{index}", "content": command, "group_openid": "testgroup",
                                 "author": {"member_openid": "tester", "user_openid": "tester"},
                                 "timestamp": datetime.now(timezone.utc).isoformat()}}
                body = json.dumps(payload).encode()
                timestamp = str(int(time.time()))
                signature = key_from_secret(secret).sign(timestamp.encode() + body).hex()
                response = client.post("/qqbot/callback", content=body, headers={"X-Bot-Appid": "123", "X-Signature-Timestamp": timestamp, "X-Signature-Ed25519": signature})
                assert response.json() == {"op": 12, "d": 0}
                client.portal.call(app.state.delivery.once)
            if app.state.source:
                if first_scene_requests is None:
                    first_scene_requests = app.state.source.requests
                else:
                    assert app.state.source.requests == first_scene_requests, "cached C2C queries requested the website again"
        health = client.get("/health/ready").json()
        assert health["delivery"] == {"sent": 10}
        images = list(Path("/state/images").glob("*.png"))
        for path in images:
            with Image.open(io.BytesIO(client.get("/qqbot/images/" + path.name).content)) as image:
                image.load()
                assert image.width == 900 and image.height <= 2500
    asyncio.run(http.aclose())
    print(json.dumps({"passed": True, "uid": os.getuid(), "python": platform.python_version(), "font": find_font(),
                      "symbolFallbackPassed": True, "groupAndC2CQueries": 10, "imageReplies": len(replies),
                      "uniqueImages": len(images), "health": health, "realQQMessagesSent": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
