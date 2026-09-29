from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.object_store import (  # noqa: E402
    FileObjectStore,
    ObjectStoreError,
)
from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    Region,
    VersionVector,
)
from tools.resource_pipeline.release_repository import (  # noqa: E402
    ReleaseRepository,
    ReleaseRepositoryError,
)


class FileObjectStoreTest(unittest.TestCase):
    def test_put_stream_deduplicates_content_by_sha256(self) -> None:
        payload = b"same immutable resource"
        expected_hash = hashlib.sha256(payload).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            store = FileObjectStore(Path(temporary))

            first = store.put_stream(
                io.BytesIO(payload),
                job_id="job-1",
                expected_sha256=expected_hash,
            )
            second = store.put_stream(
                io.BytesIO(payload),
                job_id="job-2",
                expected_sha256=expected_hash,
            )

            self.assertEqual(first.sha256, expected_hash)
            self.assertEqual(first.path, second.path)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(first.path.read_bytes(), payload)
            self.assertEqual(
                list((Path(temporary) / "store/sha256").rglob(expected_hash)),
                [first.path],
            )

    def test_hash_mismatch_leaves_no_committed_or_partial_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = FileObjectStore(root)

            with self.assertRaisesRegex(ObjectStoreError, "SHA-256 mismatch"):
                store.put_stream(
                    io.BytesIO(b"corrupt download"),
                    job_id="job-corrupt",
                    expected_sha256="0" * 64,
                )

            self.assertFalse((root / "store/sha256").exists())
            self.assertEqual(list((root / "work").rglob("*.part")), [])

    def test_reads_objects_only_through_verified_hash_interface(self) -> None:
        payload = b"read through object interface"
        expected_hash = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            store = FileObjectStore(Path(temporary))
            store.put_stream(
                io.BytesIO(payload),
                job_id="job-read",
                expected_sha256=expected_hash,
            )

            self.assertTrue(store.has_object(expected_hash))
            self.assertEqual(
                store.object_metadata(expected_hash).byte_size,
                len(payload),
            )
            with store.open_object(expected_hash) as stream:
                self.assertEqual(stream.read(), payload)


class ReleaseRepositoryTest(unittest.TestCase):
    def test_writes_region_scoped_manifest_once(self) -> None:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.global.fixture",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="f" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="global-staging-fixture-basic",
        )
        release = ContentRelease.for_client_build(
            build,
            VersionVector(
                client_version="0.9.0+8135",
                minimum_client_version=None,
                bootstrap_revision="bootstrap-1",
                catalog_hash="catalog-1",
                master_version="master-1",
                asset_manifest_version=None,
                remote_code_hash=None,
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root)
            path = repository.create_candidate(
                release,
                {"objects": [{"sha256": "a" * 64}]},
            )

            self.assertEqual(
                path,
                root
                / "releases"
                / "global"
                / "staging"
                / release.id
                / "manifest.json",
            )
            manifest = repository.load_manifest(
                Region.GLOBAL,
                Channel.STAGING,
                release.id,
            )
            self.assertEqual(manifest["contentRelease"]["id"], release.id)
            self.assertEqual(manifest["status"], "candidate")
            with self.assertRaisesRegex(
                ReleaseRepositoryError,
                "already exists",
            ):
                repository.create_candidate(release, {"objects": []})


if __name__ == "__main__":
    unittest.main()
