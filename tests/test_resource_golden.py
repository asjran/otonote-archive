from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.golden import (  # noqa: E402
    GoldenClientFacts,
    GoldenError,
    GoldenInputs,
    GoldenRegistry,
)
from tools.resource_pipeline.models import Channel, Region  # noqa: E402


class GoldenRegistryTest(unittest.TestCase):
    def _fixture(self, root: Path) -> GoldenInputs:
        inputs = root / "inputs"
        master_root = inputs / "master-json"
        master_root.mkdir(parents=True)
        files = {
            "client.apk": b"synthetic apk",
            "libil2cpp.so": b"synthetic il2cpp",
            "global-metadata.dat": b"synthetic metadata",
            "catalog_main.bin": b"synthetic catalog",
            "catalog_main.cached_hash": b"catalog-v1\n",
            "MasterDataSystemVersion.txt": b"master-v1\n",
        }
        for name, payload in files.items():
            (inputs / name).write_bytes(payload)
        (master_root / "MasterLiveMusic.json").write_text(
            json.dumps({"_allData": [{"_id": 1}, {"_id": 2}]}),
            encoding="utf-8",
        )
        (master_root / "MasterCharacter.json").write_text(
            json.dumps({"_allData": [{"_id": 10}]}),
            encoding="utf-8",
        )
        for table_name in (
            "MasterBand",
            "MasterLiveCharacter",
            "MasterLiveMusicCategory",
            "MasterLiveMusicScore",
            "MasterTag",
            "MasterText",
        ):
            (master_root / f"{table_name}.json").write_text(
                json.dumps({"_allData": []}),
                encoding="utf-8",
            )
        asset_manifest = inputs / "manifest.json"
        asset_manifest.write_text(
            json.dumps(
                {
                    "bundle_count": 3,
                    "exported": {"Sprite": 2, "TextAsset": 1},
                    "assets": [{"name": "a"}, {"name": "b"}],
                }
            ),
            encoding="utf-8",
        )
        return GoldenInputs(
            apk=inputs / "client.apk",
            il2cpp=inputs / "libil2cpp.so",
            metadata=inputs / "global-metadata.dat",
            catalog=inputs / "catalog_main.bin",
            catalog_hash=inputs / "catalog_main.cached_hash",
            master_version=inputs / "MasterDataSystemVersion.txt",
            master_root=master_root,
            asset_manifest=asset_manifest,
        )

    def test_registers_and_verifies_a_synthetic_offline_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=root / "catalog/baseline.json",
            )
            result = registry.register(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                inputs=self._fixture(root),
                client=GoldenClientFacts(
                    package_name="com.example.staging",
                    version_name="0.9.0",
                    version_code=8135,
                    unity_version="6000.3.12f1",
                    metadata_version=39,
                    auth_profile_ref="example-basic",
                ),
            )

            self.assertTrue(result.baseline_path.is_file())
            baseline = json.loads(result.baseline_path.read_text(encoding="utf-8"))
            self.assertEqual(baseline["identity"]["region"], "global")
            self.assertEqual(baseline["statistics"]["masterTableCount"], 8)
            self.assertEqual(baseline["statistics"]["masterRowCount"], 3)
            self.assertEqual(baseline["statistics"]["bundleCount"], 3)
            self.assertEqual(baseline["statistics"]["extractedResourceCount"], 2)
            self.assertEqual(
                baseline["objects"]["apk"]["sha256"],
                hashlib.sha256(b"synthetic apk").hexdigest(),
            )

            verified = registry.verify()
            self.assertEqual(verified.content_release_id, result.content_release_id)
            self.assertEqual(verified.verified_object_count, 15)

    def test_registration_rejects_missing_inputs_and_unconfirmed_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self._fixture(root)
            inputs.catalog.unlink()
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=root / "catalog/baseline.json",
            )
            client = GoldenClientFacts(
                package_name="com.example.staging",
                version_name="0.9.0",
                version_code=8135,
                unity_version="6000.3.12f1",
                metadata_version=39,
                auth_profile_ref="example-basic",
            )

            with self.assertRaisesRegex(GoldenError, "missing Golden input: catalog"):
                registry.register(
                    region=Region.GLOBAL,
                    channel=Channel.STAGING,
                    inputs=inputs,
                    client=client,
                )

            inputs.catalog.write_bytes(b"synthetic catalog")
            with self.assertRaisesRegex(GoldenError, "explicitly confirmed"):
                registry.register(
                    region=None,  # type: ignore[arg-type]
                    channel=Channel.STAGING,
                    inputs=inputs,
                    client=client,
                )

    def test_registration_requires_tables_used_by_the_current_site_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self._fixture(root)
            (inputs.master_root / "MasterText.json").unlink()
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=root / "catalog/baseline.json",
            )

            with self.assertRaisesRegex(GoldenError, "MasterText"):
                registry.register(
                    region=Region.GLOBAL,
                    channel=Channel.STAGING,
                    inputs=inputs,
                    client=GoldenClientFacts(
                        package_name="com.example.staging",
                        version_name="0.9.0",
                        version_code=8135,
                        unity_version="6000.3.12f1",
                        metadata_version=39,
                        auth_profile_ref="example-basic",
                    ),
                )

    def test_verification_detects_a_changed_catalog_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "catalog/baseline.json"
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=baseline_path,
            )
            registry.register(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                inputs=self._fixture(root),
                client=GoldenClientFacts(
                    package_name="com.example.staging",
                    version_name="0.9.0",
                    version_code=8135,
                    unity_version="6000.3.12f1",
                    metadata_version=39,
                    auth_profile_ref="example-basic",
                ),
            )
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["versionVector"]["catalogHash"] = "unexpected-catalog"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

            with self.assertRaisesRegex(GoldenError, "version vector"):
                registry.verify()

    def test_public_baseline_is_path_and_secret_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "catalog/baseline.json"
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=baseline_path,
            )
            registry.register(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                inputs=self._fixture(root),
                client=GoldenClientFacts(
                    package_name="com.example.staging",
                    version_name="0.9.0",
                    version_code=8135,
                    unity_version="6000.3.12f1",
                    metadata_version=39,
                    auth_profile_ref="do-not-publish-this-secret-ref",
                ),
            )

            serialized = baseline_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("do-not-publish-this-secret-ref", serialized)
            self.assertNotIn("_allData", serialized)

    def test_verification_detects_a_changed_primary_object_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "catalog/baseline.json"
            registry = GoldenRegistry(
                data_root=root / "private-data",
                baseline_path=baseline_path,
            )
            registry.register(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                inputs=self._fixture(root),
                client=GoldenClientFacts(
                    package_name="com.example.staging",
                    version_name="0.9.0",
                    version_code=8135,
                    unity_version="6000.3.12f1",
                    metadata_version=39,
                    auth_profile_ref="example-basic",
                ),
            )
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["objects"]["apk"]["sha256"] = "0" * 64
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

            with self.assertRaisesRegex(GoldenError, "object summary"):
                registry.verify()


if __name__ == "__main__":
    unittest.main()
