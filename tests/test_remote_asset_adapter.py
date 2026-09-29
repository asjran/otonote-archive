from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.asset_adapter import (  # noqa: E402
    AssetAdapter,
    AssetDownloadError,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter  # noqa: E402
from tools.resource_pipeline.object_store import FileObjectStore  # noqa: E402
from tools.resource_pipeline.transport import DownloadReceipt, TransportError  # noqa: E402


CATALOG = REPO_ROOT / "tests/fixtures/resource_pipeline/catalog/minimal-catalog.json"


class _DownloadTransport:
    def __init__(self, payloads: dict[str, bytes], *, fail_first: bool = False, ignore_range: bool = False):
        self.payloads = payloads
        self.fail_first = fail_first
        self.ignore_range = ignore_range
        self.calls: list[object] = []

    def download(self, request: object, output: object) -> DownloadReceipt:
        self.calls.append(request)
        payload = self.payloads[request.url]
        range_header = request.headers.get("Range")
        if self.fail_first and len(self.calls) == 1:
            output.write(payload[:4])
            raise TransportError("simulated interruption")
        if range_header and not self.ignore_range:
            offset = int(range_header.removeprefix("bytes=").removesuffix("-"))
            body = payload[offset:]
            output.write(body)
            return DownloadReceipt(206, {"content-range": f"bytes {offset}-{len(payload)-1}/{len(payload)}"}, len(body))
        output.write(payload)
        return DownloadReceipt(200, {}, len(payload))


class _ConcurrencyTransport(_DownloadTransport):
    def __init__(self, payloads: dict[str, bytes]):
        super().__init__(payloads)
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def download(self, request: object, output: object) -> DownloadReceipt:
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            time.sleep(0.02)
            return super().download(request, output)
        finally:
            with self._lock:
                self.active -= 1


class _EvidenceTransport(_DownloadTransport):
    def download(self, request: object, output: object) -> DownloadReceipt:
        receipt = super().download(request, output)
        return DownloadReceipt(
            receipt.status,
            {
                **receipt.headers,
                "etag": '"bundle-v2"',
                "last-modified": "Sat, 02 Aug 2026 00:00:00 GMT",
            },
            receipt.byte_size,
        )


class AssetAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = CatalogAdapter().parse(CATALOG)

    def test_label_prefetch_includes_transitive_dependencies(self) -> None:
        plan = AssetAdapter(allowed_hosts=("cdn.example.test",)).plan(
            self.snapshot, selectors=("event-1",)
        )
        self.assertEqual(tuple(item.primary_key for item in plan.items), ("dependency", "main"))

    def test_rejects_url_outside_allowlist_during_planning(self) -> None:
        with self.assertRaisesRegex(AssetDownloadError, "allowlist"):
            AssetAdapter(allowed_hosts=("other.example.test",)).plan(self.snapshot)

    def test_resolves_addressables_runtime_property_before_allowlist_check(self) -> None:
        location = self.snapshot.locations[0]
        from dataclasses import replace
        from tools.resource_pipeline.catalog_adapter import CatalogSnapshot

        catalog = CatalogSnapshot(
            self.snapshot.catalog_hash,
            (replace(location, internal_id="{RuntimePath}/bundles/dependency.bundle"),),
        )
        plan = AssetAdapter(
            allowed_hosts=("cdn.example.test",),
            runtime_properties={"RuntimePath": "https://cdn.example.test"},
        ).plan(catalog)
        self.assertEqual(
            plan.items[0].url,
            "https://cdn.example.test/bundles/dependency.bundle",
        )

    def test_current_catalog_full_plan_skips_local_asset_locations(self) -> None:
        catalog_path = REPO_ROOT / "phone_dump/device_external/files/RemoteCatalog/catalog_main.bin"
        if not catalog_path.is_file():
            self.skipTest("current staging catalog is not present")
        catalog = CatalogAdapter().parse(catalog_path)
        remote_url = next(
            location.internal_id
            for location in catalog.locations
            if location.internal_id.startswith("https://")
        )
        host = remote_url.split("/", 3)[2]

        plan = AssetAdapter(allowed_hosts=(host,)).plan(catalog)

        self.assertGreater(len(plan.items), 1000)
        self.assertGreater(len(plan.skipped_non_remote), 1000)
        self.assertEqual(
            len(plan.items) + len(plan.skipped_non_remote),
            len(catalog.locations),
        )
        self.assertTrue(all(item.url.startswith("https://") for item in plan.items))

    def test_interrupted_download_resumes_with_range(self) -> None:
        payloads = {
            "https://cdn.example.test/bundles/dependency.bundle": b"dependency",
            "https://cdn.example.test/bundles/main.bundle": b"main-content",
            "https://cdn.example.test/custom/data.bin": b"custom",
        }
        transport = _DownloadTransport(payloads, fail_first=True)
        with tempfile.TemporaryDirectory() as temporary:
            adapter = AssetAdapter(allowed_hosts=("cdn.example.test",), max_retries=2, max_concurrency=1)
            plan = adapter.plan(self.snapshot, selectors=("shared",))
            result = adapter.acquire(plan, transport=transport, object_store=FileObjectStore(Path(temporary)), job_id="resume")

        self.assertEqual(len(result.objects), 1)
        self.assertEqual(transport.calls[1].headers["Range"], "bytes=4-")

    def test_server_ignoring_range_restarts_without_duplicating_bytes(self) -> None:
        url = "https://cdn.example.test/bundles/main.bundle"
        payload = b"main-content"
        transport = _DownloadTransport({url: payload}, ignore_range=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fingerprint = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
            part = root / f"work/range/assets/main-{fingerprint}.part"
            part.parent.mkdir(parents=True)
            part.write_bytes(payload[:4])
            adapter = AssetAdapter(allowed_hosts=("cdn.example.test",), max_concurrency=1)
            plan = adapter.plan(self.snapshot, selectors=("main",), include_dependencies=False)
            result = adapter.acquire(plan, transport=transport, object_store=FileObjectStore(root), job_id="range")

        self.assertEqual(result.objects[0].byte_size, len(payload))
        self.assertEqual(transport.calls[0].headers["Range"], "bytes=4-")

    def test_hash_mismatch_retries_then_fails_without_commit(self) -> None:
        url = "https://cdn.example.test/bundles/dependency.bundle"
        transport = _DownloadTransport({url: b"wrong-data"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = AssetAdapter(allowed_hosts=("cdn.example.test",), max_retries=2, max_concurrency=1).plan(
                self.snapshot, selectors=("dependency",)
            )
            with self.assertRaisesRegex(AssetDownloadError, "retries exhausted"):
                AssetAdapter(allowed_hosts=("cdn.example.test",), max_retries=2, max_concurrency=1).acquire(
                    plan, transport=transport, object_store=FileObjectStore(root), job_id="bad-hash"
                )
            self.assertEqual(list((root / "store/sha256").rglob("*")) if (root / "store/sha256").exists() else [], [])
        self.assertEqual(len(transport.calls), 2)

    def test_content_addressed_store_deduplicates_across_releases(self) -> None:
        url = "https://cdn.example.test/bundles/main.bundle"
        payload = b"main-content"
        transport = _DownloadTransport({url: payload})
        with tempfile.TemporaryDirectory() as temporary:
            store = FileObjectStore(Path(temporary))
            adapter = AssetAdapter(allowed_hosts=("cdn.example.test",), max_concurrency=1)
            plan = adapter.plan(self.snapshot, selectors=("main",), include_dependencies=False)
            first = adapter.acquire(plan, transport=transport, object_store=store, job_id="release-1")
            second = adapter.acquire(plan, transport=transport, object_store=store, job_id="release-2")

        self.assertEqual(first.objects[0].sha256, hashlib.sha256(payload).hexdigest())
        self.assertTrue(second.objects[0].reused)
        self.assertEqual(second.objects[0].evidence_level, "locally_computed")

    def test_acquisition_never_exceeds_fixed_concurrency_cap(self) -> None:
        payloads = {
            "https://cdn.example.test/bundles/dependency.bundle": b"dependency",
            "https://cdn.example.test/bundles/main.bundle": b"main-content",
            "https://cdn.example.test/custom/data.bin": b"custom",
        }
        transport = _ConcurrencyTransport(payloads)
        with tempfile.TemporaryDirectory() as temporary:
            adapter = AssetAdapter(
                allowed_hosts=("cdn.example.test",),
                max_concurrency=2,
            )
            adapter.acquire(
                adapter.plan(self.snapshot),
                transport=transport,
                object_store=FileObjectStore(Path(temporary)),
                job_id="concurrency",
            )

        self.assertEqual(transport.maximum_active, 2)

    def test_acquisition_records_release_and_sanitized_http_evidence(self) -> None:
        from dataclasses import replace
        from tools.resource_pipeline.catalog_adapter import CatalogSnapshot

        original = self.snapshot.location_for_key("main")
        signed_url = original.internal_id + "?token=must-not-leak"
        snapshot = CatalogSnapshot(
            self.snapshot.catalog_hash,
            (replace(original, internal_id=signed_url),),
        )
        transport = _EvidenceTransport({signed_url: b"main-content"})
        with tempfile.TemporaryDirectory() as temporary:
            result = AssetAdapter(
                allowed_hosts=("cdn.example.test",),
                max_concurrency=1,
            ).acquire(
                AssetAdapter(allowed_hosts=("cdn.example.test",)).plan(
                    snapshot,
                    include_dependencies=False,
                ),
                transport=transport,
                object_store=FileObjectStore(Path(temporary)),
                job_id="global-hot-update",
                source_release_id="global-staging-release-v2",
            )

        acquired = result.objects[0]
        self.assertEqual(acquired.source_release_id, "global-staging-release-v2")
        self.assertEqual(acquired.url, original.internal_id)
        self.assertEqual(acquired.etag, '"bundle-v2"')
        self.assertEqual(
            acquired.last_modified,
            "Sat, 02 Aug 2026 00:00:00 GMT",
        )
        self.assertNotIn("must-not-leak", repr(acquired))


if __name__ == "__main__":
    unittest.main()
