"""HTTPS callback -> durable outbox -> query template -> QQ image reply."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import re
import time
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .config import Config
from .content import Content
from .query import Queries, Reply, Section
from .render import Renderer
from .store import Images, Outbox
from .website import WebsiteCache
from .transport import QQClient, QQError, challenge, verify

LOG = logging.getLogger("ournotes.qqbot")
MAX_BODY = 65536


class Delivery:
    def __init__(self, queries, renderer, outbox, images, client, public_base, source=None):
        self.source = source
        self.queries, self.renderer, self.outbox = queries, renderer, outbox
        self.images, self.client, self.public_base = images, client, public_base.rstrip("/")

    def prepare(self, command):
        try:
            content = self.source.content if self.source else None
            if self.source and content is None:
                reply = Reply("资料提示", "资料暂时不可用", sections=[Section("稍后重试", ["正在连接资料站，请稍后重新查询。"])] )
            else:
                reply = Queries(content).query(command) if content else self.queries.query(command)
                if self.source and self.source.stale:
                    reply.notice = (reply.notice + " · " if reply.notice else "") + "资料站暂不可达，正在使用已校验的缓存。"
            renderer = Renderer(content.snapshot, self.renderer.font_path) if content else self.renderer
            return renderer.render(reply)
        except Exception:
            LOG.error("query_or_render_failed")
            return self.renderer.render(Reply("查询提示", "资料暂时无法读取", sections=[Section("稍后重试", ["请稍后重新发送查询指令。"])]))

    async def once(self) -> bool:
        job = self.outbox.next()
        if not job:
            return False
        payload = json.loads(job["payload"])
        try:
            pictures = await asyncio.to_thread(self.prepare, payload["command"])
            for index, picture in enumerate(pictures):
                if index < job["sent"]:
                    continue
                if time.time() >= job["expires"]:
                    raise QQError("reply_expired")
                name = self.images.put(picture)
                await self.client.send_image(payload["scene"], payload["target"], payload["message_id"], index + 1,
                                             f"{self.public_base}/qqbot/images/{name}")
                self.outbox.sent(job["key"], index + 1)
            self.outbox.finish(job["key"])
            self.images.sweep()
        except QQError as exc:
            self.outbox.fail(job, exc.code, exc.retryable, exc.retry_after * (job["attempts"] + 1))
            LOG.warning("image_delivery_failed code=%s retryable=%s", exc.code, exc.retryable)
        except Exception:
            self.outbox.fail(job, "internal_failure", False, 0)
            LOG.error("image_delivery_internal_failure")
        return True

    async def run(self):
        while True:
            await self.once()
            await asyncio.sleep(0.5)


def create_app(config: Config, *, http: httpx.AsyncClient | None = None, run_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        resources = ExitStack()
        config.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = resources.enter_context((config.state / "worker.lock").open("a"))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            resources.close()
            raise RuntimeError("QQ bot requires one process per state directory")
        try:
            source = WebsiteCache(config.state / "website-cache", config.data_url) if config.data_url else None
            if source:
                resources.callback(source.close)
                await asyncio.to_thread(source.refresh)
            content = source.content if source else Content(config.bundle)
            renderer = Renderer(content.snapshot if content else "暂不可用", config.font)
            outbox = Outbox(config.state / "outbox.sqlite3", config.max_pending)
            resources.callback(outbox.close)
            images = Images(config.state / "images")
        except Exception:
            resources.close()
            raise
        session = http or httpx.AsyncClient(follow_redirects=False)
        client = QQClient(config.app_id, config.secret, session, config.api_base_url)
        delivery = Delivery(Queries(content) if content else None, renderer, outbox, images, client, config.public_base_url, source)
        app.state.outbox, app.state.delivery = outbox, delivery
        app.state.release_id, app.state.images = content.release_id if content else None, images
        app.state.source = source
        worker = asyncio.create_task(delivery.run()) if run_worker else None
        app.state.worker = worker
        async def refresh_source():
            while True:
                await asyncio.sleep(config.refresh_seconds)
                await asyncio.to_thread(source.refresh)
        updater = asyncio.create_task(refresh_source()) if source else None
        try:
            yield
        finally:
            if updater:
                updater.cancel()
                try:
                    await updater
                except asyncio.CancelledError:
                    pass
            if worker:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            if http is None:
                await session.aclose()
            resources.close()

    app = FastAPI(title="Our Notes QQ Bot", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        if app.state.worker and app.state.worker.done():
            raise HTTPException(503, "delivery worker stopped")
        source = app.state.source
        result = {"status": "ok", "releaseId": source.content.release_id if source and source.content else app.state.release_id,
                  "delivery": app.state.outbox.counts()}
        if source:
            result["dataSource"] = source.status()
            if source.content is None:
                return JSONResponse({**result, "status": "waiting_for_data"}, status_code=503)
        return result

    @app.get("/qqbot/images/{name}")
    async def image(name: str):
        if not re.fullmatch(r"[0-9a-f]{64}\.png", name):
            raise HTTPException(404)
        path = app.state.images.root / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"})

    @app.post("/qqbot/callback")
    async def callback(request: Request):
        if request.headers.get("X-Bot-Appid") != config.app_id:
            raise HTTPException(401, "invalid application")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "payload too large")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "invalid payload")
        if payload.get("op") == 13:
            if not isinstance(payload.get("d"), dict):
                raise HTTPException(400, "invalid challenge")
            if (request.headers.get("X-Signature-Ed25519") or request.headers.get("X-Signature-Timestamp")) and not verify(
                    config.secret, bytes(body), request.headers.get("X-Signature-Timestamp", ""), request.headers.get("X-Signature-Ed25519", "")):
                raise HTTPException(401, "invalid signature")
            token, timestamp = payload["d"].get("plain_token"), payload["d"].get("event_ts")
            if (not isinstance(token, str) or not 1 <= len(token) <= 256
                    or not isinstance(timestamp, str) or not timestamp.isdigit() or len(timestamp) > 12):
                raise HTTPException(400, "invalid challenge")
            return challenge(config.secret, token, timestamp)
        if not verify(config.secret, bytes(body), request.headers.get("X-Signature-Timestamp", ""), request.headers.get("X-Signature-Ed25519", "")):
            raise HTTPException(401, "invalid signature")
        if payload.get("op") == 1:
            seq = payload.get("d")
            if type(seq) is not int or not 0 <= seq <= 2**32 - 1:
                raise HTTPException(400, "invalid heartbeat")
            return {"op": 11, "d": seq}
        if payload.get("op") != 0 or payload.get("t") not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
            return {"op": 12, "d": 0}
        data = payload.get("d")
        if not isinstance(data, dict):
            raise HTTPException(400, "invalid event")
        author = data.get("author", {})
        if not isinstance(author, dict):
            raise HTTPException(400, "invalid author")
        scene = "groups" if payload["t"] == "GROUP_AT_MESSAGE_CREATE" else "users"
        sender = author.get("member_openid") if scene == "groups" else author.get("user_openid")
        target = data.get("group_openid") if scene == "groups" else sender
        message_id, command = data.get("id"), data.get("content")
        if (not all(isinstance(x, str) and 1 <= len(x) <= 512 for x in (sender, target, message_id))
                or not re.fullmatch(r"[A-Za-z0-9_-]+", target) or not isinstance(command, str)):
            raise HTTPException(400, "invalid message")
        try:
            timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError()
            created = timestamp.timestamp()
            if created > time.time() + 60:
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(400, "invalid message timestamp")
        if time.time() - created >= 240:
            return {"op": 12, "d": 0}
        result = app.state.outbox.enqueue({"scene": scene, "target": target, "sender": sender,
                                         "message_id": message_id, "command": command[:201], "expires": created + 240})
        if result == "full":
            return JSONResponse({"op": 12, "d": 1}, status_code=503)
        if result == "rate_limited":
            return JSONResponse({"op": 12, "d": 1}, status_code=429, headers={"Retry-After": "60"})
        return {"op": 12, "d": 0}

    return app


def create_app_from_environment():
    return create_app(Config.from_env())
