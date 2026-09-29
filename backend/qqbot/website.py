"""Versioned HTTPS data source with atomic snapshots and demand-loaded assets."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

from .content import Content, ContentError, DATA_FILES, inside
from .content_source import adapt_content

LOG = logging.getLogger("ournotes.qqbot")
DIGEST = re.compile(r"[0-9a-f]{64}")


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


class WebsiteCache:
    def __init__(self, root: Path, url: str, *, http: httpx.Client | None = None):
        self.root, self.url = root, url
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ContentError("website source requires a plain HTTPS URL")
        self.origin = (parsed.scheme, parsed.netloc)
        self.http = http or httpx.Client(timeout=15, follow_redirects=False)
        self.owns_http = http is None
        self.lock = threading.Lock()
        self.content = None
        self.revision, self.etag = "", ""
        self.source_revision = ""
        self.checked_at = 0.0
        self.stale = True
        self.failed_assets = {}
        self.requests, self.download_bytes = 0, 0
        root.mkdir(parents=True, exist_ok=True)
        self._restore()

    def close(self):
        if self.owns_http:
            self.http.close()

    def _url(self, value: str):
        result = urljoin(self.url, value)
        p = urlparse(result)
        if (p.scheme, p.netloc) != self.origin or p.username or p.password or p.query or p.fragment:
            raise ContentError("data references must stay on the configured HTTPS origin")
        return result

    def _get(self, url: str, limit: int, *, etag=""):
        self.requests += 1
        with self.http.stream("GET", self._url(url), headers={"If-None-Match": etag} if etag else {}) as response:
            if response.status_code == 304:
                return None, etag
            response.raise_for_status()
            if response.status_code != 200:
                raise ContentError("unexpected data response")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ContentError("website object exceeds size limit")
                chunks.append(chunk)
            self.download_bytes += size
            return b"".join(chunks), response.headers.get("ETag", "")

    @staticmethod
    def _verified(data, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or data is None or hashlib.sha256(data).hexdigest() != digest:
            raise ContentError("website integrity check failed")
        return data

    def _open(self, revision):
        if not isinstance(revision, str) or not DIGEST.fullmatch(revision):
            raise ContentError("invalid website revision")
        directory = self.root / "snapshots" / revision
        self._verified((directory / "manifest.json").read_bytes(), revision)
        content = Content(directory, asset_loader=lambda asset: self.asset(content, asset))
        if content.manifest.get("schemaVersion") != 2:
            raise ContentError("website requires manifest version 2")
        return content

    def _restore(self):
        try:
            state = json.loads((self.root / "active.json").read_text())
            if state.get("source") != self.url:
                return
            content = self._open(state["revision"])
            self.content, self.revision = content, state["revision"]
            self.source_revision = content.manifest.get("sourceRevision", self.revision)
            self.etag = state.get("etag", "")
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _blob(self, digest, url):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ContentError("invalid file digest")
        cached = self.root / "blobs" / digest
        try:
            return self._verified(cached.read_bytes(), digest)
        except (OSError, ContentError):
            data, _ = self._get(url, 16 * 1024 * 1024)
            atomic(cached, self._verified(data, digest))
            return data

    def refresh(self):
        """Called at startup and on a timer, never per user query."""
        try:
            raw, etag = self._get(self.url, 4096, etag=self.etag if self.content else "")
            if raw is None:
                if self.content is None:
                    raise ContentError("304 without cached data")
                self.stale, self.checked_at = False, time.time()
                return False
            pointer = json.loads(raw)
            independent = "contentReleaseId" in pointer
            source_revision = pointer["sha256"] if independent else pointer["revision"]
            if not isinstance(source_revision, str) or not DIGEST.fullmatch(source_revision):
                raise ContentError("invalid website revision")
            if self.content is not None and source_revision == self.source_revision:
                self.etag, self.stale, self.checked_at = etag, False, time.time()
                return False
            blob, _ = self._get(pointer["manifest"], 1024 * 1024)
            manifest = json.loads(self._verified(blob, source_revision))
            if independent:
                manifest = adapt_content(self, pointer, manifest)
                blob = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            revision = hashlib.sha256(blob).hexdigest()
            if manifest.get("schemaVersion") != 2 or set(manifest["files"]) != {*DATA_FILES, "game-database.json"}:
                raise ContentError("invalid website file set")
            directory = self.root / "snapshots" / revision
            for name, digest in manifest["files"].items():
                path = inside(directory, name)
                atomic(path, self._blob(digest, manifest["fileUrls"][name]))
            atomic(directory / "manifest.json", blob)
            candidate = self._open(revision)
            if independent and candidate.release_id != pointer['contentReleaseId']:
                raise ContentError("content pointer release mismatch")
            atomic(self.root / "active.json", json.dumps({"source": self.url, "revision": revision, "etag": etag}).encode())
            # Readers keep their old immutable Content until their render completes.
            self.content, self.revision, self.etag = candidate, revision, etag
            self.source_revision = source_revision
            self.stale, self.checked_at = False, time.time()
            self._trim_snapshots()
            return True
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
            self.stale = True
            LOG.warning("website_refresh_failed type=%s", type(exc).__name__)
            return False

    def _trim_snapshots(self):
        # Keep current and one predecessor; renderers retain already-loaded data.
        directories = sorted((self.root / "snapshots").iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        keep = {self.revision}
        for p in directories:
            if p.is_dir() and DIGEST.fullmatch(p.name) and len(keep) < 2:
                keep.add(p.name)
        referenced = set()
        for p in directories:
            if p.is_dir() and DIGEST.fullmatch(p.name):
                if p.name not in keep:
                    shutil.rmtree(p)
                else:
                    try:
                        manifest = json.loads((p / "manifest.json").read_text())
                        referenced.update(manifest["files"].values())
                        referenced.update(manifest.get("sourceFiles", {}).values())
                    except (OSError, ValueError, KeyError):
                        pass
        for p in (self.root / "blobs").glob("*"):
            if p.name not in referenced and DIGEST.fullmatch(p.name):
                p.unlink(missing_ok=True)

    def asset(self, content, asset_id):
        descriptor = content.manifest["remoteAssets"].get(asset_id)
        if descriptor is None:
            return None
        digest = descriptor["sha256"]
        target = self.root / "assets" / (digest + descriptor["suffix"])
        with self.lock:
            if target.is_file():
                if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                    target.touch()
                    return target
                target.unlink()
            if self.failed_assets.get(digest, 0) > time.monotonic():
                return None
            try:
                data, _ = self._get(descriptor["url"], 5 * 1024 * 1024)
                atomic(target, self._verified(data, digest))
                with Image.open(target) as picture:
                    if picture.width * picture.height > 20_000_000:
                        raise ContentError("asset pixel budget exceeded")
                    picture.verify()
                self.failed_assets.pop(digest, None)
                self._trim_assets(target)
                return target
            except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
                target.unlink(missing_ok=True)
                self.failed_assets[digest] = time.monotonic() + 60
                LOG.warning("website_asset_unavailable")
                return None

    def _trim_assets(self, keep):
        paths = sorted((self.root / "assets").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for p in paths:
            total += p.stat().st_size
            if total > 256 * 1024 * 1024 and p != keep:
                p.unlink(missing_ok=True)

    def status(self):
        return {"mode": "https-cache", "revision": self.revision, "stale": self.stale,
                "source": self.url, "sourceRevision": self.source_revision,
                "checkedAt": self.checked_at, "requests": self.requests, "downloadBytes": self.download_bytes}
