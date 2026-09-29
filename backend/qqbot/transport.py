"""Official QQ HTTPS transport. No text-message fallback exists."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def key_from_secret(secret: str) -> Ed25519PrivateKey:
    seed = secret.encode("utf-8")
    if not seed:
        raise ValueError("empty QQ secret")
    while len(seed) < 32:
        seed *= 2
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def challenge(secret: str, plain_token: str, event_ts: str) -> dict:
    signature = key_from_secret(secret).sign((event_ts + plain_token).encode()).hex()
    return {"plain_token": plain_token, "signature": signature}


def verify(secret: str, body: bytes, timestamp: str, signature: str, now: float | None = None) -> bool:
    try:
        current = time.time() if now is None else now
        if len(timestamp) > 12 or len(signature) != 128 or not timestamp.isdigit() or not -60 <= current - int(timestamp) <= 300:
            return False
        key_from_secret(secret).public_key().verify(bytes.fromhex(signature), timestamp.encode() + body)
        return True
    except (ValueError, InvalidSignature):
        return False


class QQError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: float = 2):
        super().__init__(code)
        self.code, self.retryable = code, retryable
        self.retry_after = min(60, max(1, retry_after))


class QQClient:
    def __init__(self, app_id: str, secret: str, http: httpx.AsyncClient, api_base_url="https://api.bot.qq.com"):
        self.app_id, self.secret, self.http, self.base = app_id, secret, http, api_base_url
        self.token, self.expires = "", 0.0
        self.lock = asyncio.Lock()

    async def _request(self, url: str, body: dict, headers: dict | None = None) -> dict:
        try:
            response = await self.http.post(url, json=body, headers=headers, timeout=12)
        except httpx.HTTPError as exc:
            raise QQError("transport_failure", retryable=True) from exc
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", 5))
            except ValueError:
                delay = 5
            raise QQError("http_429", retryable=True, retry_after=delay)
        if response.status_code == 401:
            raise QQError("http_401")
        if response.status_code >= 500:
            raise QQError("upstream_unavailable", retryable=True)
        if not 200 <= response.status_code < 300:
            raise QQError(f"http_{response.status_code}")
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            raise QQError("invalid_response") from exc
        code = data.get("code", data.get("err_code", 0))
        if code not in (None, 0, "0"):
            # Only record the code; upstream messages may contain credentials or IDs.
            safe_code = str(code) if str(code).isdigit() else "unknown"
            raise QQError(f"api_{safe_code}", retryable=str(code) in ("100001", "850027", "40093001"), retry_after=5)
        return data

    async def access_token(self) -> str:
        async with self.lock:
            if self.token and time.monotonic() < self.expires:
                return self.token
            data = await self._request("https://api.bot.qq.com/app/getAppAccessToken",
                                       {"appId": self.app_id, "clientSecret": self.secret})
            try:
                token, ttl = data["access_token"], int(data["expires_in"])
                if not isinstance(token, str) or not token or ttl <= 0:
                    raise ValueError()
            except (KeyError, ValueError, TypeError) as exc:
                raise QQError("invalid_token_response") from exc
            self.token = token
            self.expires = time.monotonic() + max(1, ttl - min(60, ttl / 2))
            return token

    async def api(self, path: str, payload: dict) -> dict:
        for attempt in range(2):
            token = await self.access_token()
            try:
                return await self._request(self.base + path, payload, {"Authorization": f"QQBot {token}"})
            except QQError as exc:
                if exc.code == "http_401" and attempt == 0:
                    self.token = ""
                    continue
                raise
        raise QQError("authentication_failed")

    async def send_image(self, scene: str, target: str, message_id: str, seq: int, url: str) -> None:
        if scene not in ("groups", "users"):
            raise ValueError("invalid QQ scene")
        path = f"/v2/{scene}/{quote(target, safe='')}"
        uploaded = await self.api(path + "/files", {"file_type": 1, "url": url, "srv_send_msg": False})
        file_info = uploaded.get("file_info")
        if not isinstance(file_info, str) or not file_info:
            raise QQError("missing_file_info")
        result = await self.api(path + "/messages", {"msg_type": 7, "media": {"file_info": file_info},
                                                     "msg_id": message_id, "msg_seq": seq})
        if not result.get("id"):
            raise QQError("missing_message_id")
