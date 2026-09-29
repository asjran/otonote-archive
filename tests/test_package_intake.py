from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.package_intake import (
    PackageIntakeError,
    aggregate_asset_manifests,
    build_package_set_manifest,
    parse_apksigner_output,
)


CERT = "0123456789abcdef" * 4


class PackageIntakeTest(unittest.TestCase):
    def test_parses_apksigner_fixture_without_external_process(self) -> None:
        text = (REPO_ROOT / "tests/fixtures/resource_pipeline/package-intake/apksigner-output.txt").read_text()
        self.assertEqual(parse_apksigner_output(text), CERT)

    def test_builds_stable_complete_split_set_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, body in (("split_config.arm64_v8a.apk", b"arm"), ("base.apk", b"base"), ("split_UnityDataAssetPack.apk", b"asset")):
                (root / name).write_bytes(body)
            facts = {
                "base.apk": {"packageName": "com.bilibili.sirius", "versionName": "0.3.2", "versionCode": 12, "splitName": None, "certificateSha256": CERT},
                "split_UnityDataAssetPack.apk": {"packageName": "com.bilibili.sirius", "versionName": "0.3.2", "versionCode": 12, "splitName": "UnityDataAssetPack", "certificateSha256": CERT},
                "split_config.arm64_v8a.apk": {"packageName": "com.bilibili.sirius", "versionName": "0.3.2", "versionCode": 12, "splitName": "config.arm64_v8a", "certificateSha256": CERT},
            }
            manifest = build_package_set_manifest(root, region="global", channel="staging", inspector=lambda p: facts[p.name])
            self.assertEqual([x["logicalName"] for x in manifest["splits"]], ["base", "UnityDataAssetPack", "config.arm64_v8a"])
            self.assertEqual(manifest["packageName"], "com.bilibili.sirius")
            self.assertNotIn(str(root), json.dumps(manifest))
            canonical = dict(manifest); digest = canonical.pop("packageSetSha256")
            expected = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(digest, expected)

    def test_rejects_incomplete_or_inconsistent_split_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "base.apk").write_bytes(b"base")
            facts = {"packageName": "p", "versionName": "1", "versionCode": 1, "splitName": None, "certificateSha256": CERT}
            with self.assertRaisesRegex(PackageIntakeError, "Asset Pack"):
                build_package_set_manifest(root, region="global", channel="staging", inspector=lambda _p: facts)

    def test_aggregates_export_paths_relative_to_the_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle-a"
            (bundle / "textures").mkdir(parents=True)
            (bundle / "textures/1.png").write_bytes(b"png")
            (bundle / "manifest.json").write_text(json.dumps({"objects": [{
                "path_id": 7,
                "type": "Texture2D",
                "name": "preview",
                "exported_file": "textures/1.png",
            }]}), encoding="utf-8")
            manifest = aggregate_asset_manifests(root, catalog_sha256="a" * 64)
            self.assertEqual(manifest["assets"][0]["exported_file"], "bundle-a/textures/1.png")
            self.assertEqual(manifest["assets"][0]["path"], "bundle-a/textures/1.png")
            self.assertEqual(manifest["assets"][0]["byteSize"], 3)


if __name__ == "__main__":
    unittest.main()
