"""Dependency-aware, resumable Addressables asset acquisition."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from tools.resource_pipeline.catalog_adapter import CatalogLocation, CatalogSnapshot
from tools.resource_pipeline.object_store import FileObjectStore, ObjectStoreError
from tools.resource_pipeline.transport import HttpRequest


class AssetDownloadError(RuntimeError):
    """Raised when a download plan or acquisition cannot be completed safely."""


@dataclass(frozen=True)
class AssetDownloadItem:
    primary_key: str
    url: str
    dependencies: tuple[str, ...]
    expected_sha256: str | None
    expected_size: int | None


@dataclass(frozen=True)
class AssetDownloadPlan:
    catalog_hash: str
    selectors: tuple[str, ...]
    items: tuple[AssetDownloadItem, ...]
    skipped_non_remote: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcquiredAsset:
    primary_key: str
    url: str
    sha256: str
    byte_size: int
    reused: bool
    evidence_level: str
    source_release_id: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class AssetAcquisition:
    objects: tuple[AcquiredAsset, ...]


class DownloadTransport(Protocol):
    def download(self, request: HttpRequest, output: Any) -> Any: ...


class AssetAdapter:
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        max_concurrency: int = 4,
        max_retries: int = 3,
        runtime_properties: Mapping[str, str] | None = None,
    ):
        hosts = frozenset(host.lower().strip() for host in allowed_hosts)
        if not hosts or "" in hosts:
            raise ValueError("allowed_hosts cannot be empty")
        if not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrency must be between 1 and 16")
        if not 1 <= max_retries <= 10:
            raise ValueError("max_retries must be between 1 and 10")
        self._allowed_hosts = hosts
        self._max_concurrency = max_concurrency
        self._max_retries = max_retries
        self._runtime_properties = dict(runtime_properties or {})

    def plan(
        self,
        catalog: CatalogSnapshot,
        *,
        selectors: tuple[str, ...] = (),
        include_dependencies: bool = True,
    ) -> AssetDownloadPlan:
        by_primary: dict[str, list[CatalogLocation]] = {}
        for location in catalog.locations:
            by_primary.setdefault(location.primary_key, []).append(location)
        selected: dict[tuple[str, str, str], CatalogLocation] = {}
        if selectors:
            for selector in selectors:
                matches = catalog.locations_for_selector(selector)
                if not matches:
                    raise AssetDownloadError(f"Catalog selector was not found: {selector}")
                for location in matches:
                    selected[_location_identity(location)] = location
        else:
            selected = {
                _location_identity(location): location for location in catalog.locations
            }

        if include_dependencies:
            pending = list(selected.values())
            while pending:
                location = pending.pop()
                for dependency in location.dependencies:
                    dep_locations = by_primary.get(dependency, ())
                    if not dep_locations:
                        raise AssetDownloadError(
                            f"Catalog dependency was not found: {dependency}"
                        )
                    for dep_location in dep_locations:
                        identity = _location_identity(dep_location)
                        if identity not in selected:
                            selected[identity] = dep_location
                            pending.append(dep_location)

        ordered = self._topological_order(selected)
        items = []
        skipped_non_remote = []
        for location in ordered:
            resolved_url = self._resolve_internal_id(location.internal_id)
            parsed = urllib.parse.urlsplit(resolved_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme.lower() not in {"http", "https"}:
                skipped_non_remote.append(location.primary_key)
                continue
            if host not in self._allowed_hosts:
                raise AssetDownloadError(
                    f"asset URL is outside the environment allowlist: {host or '<missing>'}"
                )
            expected_sha256 = (
                location.expected_hash
                if location.expected_hash_algorithm == "sha256"
                and _is_sha256(location.expected_hash)
                else None
            )
            items.append(
                AssetDownloadItem(
                    primary_key=location.primary_key,
                    url=resolved_url,
                    dependencies=location.dependencies,
                    expected_sha256=expected_sha256,
                    expected_size=location.expected_size,
                )
            )
        return AssetDownloadPlan(
            catalog.catalog_hash,
            tuple(selectors),
            tuple(items),
            tuple(skipped_non_remote),
        )

    def _resolve_internal_id(self, internal_id: str) -> str:
        resolved = internal_id
        for name, value in self._runtime_properties.items():
            resolved = resolved.replace("{" + name + "}", value.rstrip("/"))
        return resolved

    def acquire(
        self,
        plan: AssetDownloadPlan,
        *,
        transport: DownloadTransport,
        object_store: FileObjectStore,
        job_id: str,
        source_release_id: str | None = None,
    ) -> AssetAcquisition:
        results: dict[AssetDownloadItem, AcquiredAsset] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(max_workers=self._max_concurrency) as executor:
            futures = {
                executor.submit(
                    self._acquire_one,
                    item,
                    transport=transport,
                    object_store=object_store,
                    job_id=job_id,
                    source_release_id=source_release_id,
                ): item
                for item in plan.items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    results[item] = future.result()
                except Exception as error:
                    errors.append((item.primary_key, error))
        if errors:
            primary_key, error = errors[0]
            raise AssetDownloadError(
                f"asset retries exhausted for {primary_key}: {type(error).__name__}: {error}"
            ) from None
        return AssetAcquisition(
            tuple(results[item] for item in plan.items)
        )

    def _acquire_one(
        self,
        item: AssetDownloadItem,
        *,
        transport: DownloadTransport,
        object_store: FileObjectStore,
        job_id: str,
        source_release_id: str | None,
    ) -> AcquiredAsset:
        if item.expected_sha256 and object_store.has_object(item.expected_sha256):
            metadata = object_store.object_metadata(item.expected_sha256)
            if item.expected_size is not None and metadata.byte_size != item.expected_size:
                raise AssetDownloadError("stored object does not match expected size")
            return AcquiredAsset(
                primary_key=item.primary_key,
                url=_safe_source_uri(item.url),
                sha256=metadata.sha256,
                byte_size=metadata.byte_size,
                reused=True,
                evidence_level="catalog_sha256",
                source_release_id=source_release_id,
                etag=None,
                last_modified=None,
            )

        part_dir = object_store.work_root / job_id / "assets"
        part_dir.mkdir(parents=True, exist_ok=True)
        url_fingerprint = hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:12]
        part = part_dir / f"{_safe_key(item.primary_key)}-{url_fingerprint}.part"
        last_error: Exception | None = None
        for _ in range(self._max_retries):
            try:
                receipt = self._download_attempt(item, part, transport)
                size = part.stat().st_size
                if item.expected_size is not None and size != item.expected_size:
                    raise AssetDownloadError(
                        f"download size mismatch: expected {item.expected_size}, got {size}"
                    )
                with part.open("rb") as stream:
                    stored = object_store.put_stream(
                        stream,
                        job_id=job_id,
                        expected_sha256=item.expected_sha256,
                    )
                part.unlink(missing_ok=True)
                return AcquiredAsset(
                    primary_key=item.primary_key,
                    url=_safe_source_uri(item.url),
                    sha256=stored.sha256,
                    byte_size=stored.byte_size,
                    reused=stored.reused,
                    evidence_level=(
                        "catalog_sha256"
                        if item.expected_sha256
                        else "locally_computed"
                    ),
                    source_release_id=source_release_id,
                    etag=receipt.headers.get("etag"),
                    last_modified=receipt.headers.get("last-modified"),
                )
            except ObjectStoreError as error:
                last_error = error
                part.unlink(missing_ok=True)
            except Exception as error:
                last_error = error
                if isinstance(error, AssetDownloadError) and "size mismatch" in str(error):
                    part.unlink(missing_ok=True)
        raise last_error or AssetDownloadError("download did not start")

    @staticmethod
    def _download_attempt(
        item: AssetDownloadItem,
        part: Path,
        transport: DownloadTransport,
    ) -> Any:
        offset = part.stat().st_size if part.exists() else 0
        if offset == 0:
            with part.open("wb") as output:
                receipt = transport.download(HttpRequest("GET", item.url), output)
            if receipt.status not in {200, 206}:
                raise AssetDownloadError(f"unexpected download status {receipt.status}")
            return receipt

        response_part = part.with_suffix(".response.part")
        response_part.unlink(missing_ok=True)
        try:
            with response_part.open("wb") as output:
                receipt = transport.download(
                    HttpRequest("GET", item.url, headers={"Range": f"bytes={offset}-"}),
                    output,
                )
            if receipt.status == 206:
                content_range = receipt.headers.get("content-range", "")
                if content_range and not content_range.startswith(f"bytes {offset}-"):
                    raise AssetDownloadError("server returned an inconsistent Content-Range")
                with part.open("ab") as output, response_part.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            elif receipt.status == 200:
                os.replace(response_part, part)
            else:
                raise AssetDownloadError(f"unexpected resume status {receipt.status}")
            return receipt
        finally:
            response_part.unlink(missing_ok=True)

    @staticmethod
    def _topological_order(
        selected: dict[tuple[str, str, str], CatalogLocation]
    ) -> tuple[CatalogLocation, ...]:
        ordered: list[CatalogLocation] = []
        visiting: set[tuple[str, str, str]] = set()
        visited: set[tuple[str, str, str]] = set()
        selected_by_primary: dict[str, list[CatalogLocation]] = {}
        for selected_location in selected.values():
            selected_by_primary.setdefault(
                selected_location.primary_key, []
            ).append(selected_location)

        def visit(location: CatalogLocation) -> None:
            identity = _location_identity(location)
            if identity in visited:
                return
            if identity in visiting:
                raise AssetDownloadError(f"Catalog dependency cycle: {location.primary_key}")
            visiting.add(identity)
            for dependency in location.dependencies:
                for dependency_location in selected_by_primary.get(dependency, ()):
                    visit(dependency_location)
            visiting.remove(identity)
            visited.add(identity)
            ordered.append(location)

        for location in selected.values():
            visit(location)
        return tuple(ordered)


def _safe_key(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (safe or "asset")[:100]


def _is_sha256(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-f]{64}", value))


def _safe_source_uri(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def _location_identity(location: CatalogLocation) -> tuple[str, str, str]:
    return location.internal_id, location.provider_id, location.resource_type
