from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.object_store import FileObjectStore  # noqa: E402
from tools.resource_pipeline.validation import ContentValidator  # noqa: E402


def _manifest(objects: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "candidate",
        "clientBuild": {"id": "global-staging-android-1-aaaaaaaaaaaaaaaa"},
        "contentRelease": {
            "id": "global-staging-candidate",
            "region": "global",
            "channel": "staging",
            "observedByClientBuildRef": "global-staging-android-1-aaaaaaaaaaaaaaaa",
            "versionVector": {
                "clientVersion": "1.0.0",
                "minimumClientVersion": None,
                "bootstrapRevision": None,
                "catalogHash": "catalog-v1",
                "masterVersion": "master-v1",
                "assetManifestVersion": None,
                "remoteCodeHash": None,
            },
        },
        "evidence": {
            "catalogHash": "catalog-v1",
            "masterVersion": "master-v1",
            "assetManifestVersion": None,
        },
        "objects": objects,
        "statistics": {
            "criticalTableRows": {
                "MasterLiveMusic": 100,
                "MasterMemberCard": 100,
                "MasterEvent": 10,
            }
        },
        "entities": [],
        "references": [],
        "approvals": {},
    }


class ContentValidatorTest(unittest.TestCase):
    def test_reports_missing_size_and_hash_corruption_for_required_objects(self) -> None:
        payload = b"catalog bytes"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            store = FileObjectStore(Path(temporary))
            store.put_stream(io.BytesIO(payload), job_id="validation", expected_sha256=digest)
            stored_path = store.object_path(digest)
            stored_path.write_bytes(b"tampered")
            candidate = _manifest(
                [
                    {
                        "role": "catalog",
                        "logicalName": "catalog.bin",
                        "sha256": digest,
                        "byteSize": len(payload) + 1,
                    },
                    {
                        "role": "masterTable",
                        "logicalName": "MasterLiveMusic.json",
                        "sha256": "f" * 64,
                        "byteSize": 10,
                    },
                ]
            )

            report = ContentValidator(object_store=store).validate(candidate)

        codes = {issue.code for issue in report.issues}
        self.assertFalse(report.valid)
        self.assertIn("object_size_mismatch", codes)
        self.assertIn("object_hash_mismatch", codes)
        self.assertIn("object_missing", codes)

    def test_rejects_cross_server_identity_and_version_evidence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = _manifest([])
            candidate["contentRelease"]["channel"] = "production"
            candidate["evidence"]["catalogHash"] = "different-catalog"
            candidate["evidence"]["masterVersion"] = "different-master"

            report = ContentValidator(
                object_store=FileObjectStore(Path(temporary))
            ).validate(candidate)

        codes = {issue.code for issue in report.issues}
        self.assertIn("identity_mismatch", codes)
        self.assertIn("version_evidence_mismatch", codes)

    def test_rejects_empty_or_large_critical_master_table_drops(self) -> None:
        baseline = _manifest([])
        candidate = _manifest([])
        candidate["statistics"]["criticalTableRows"] = {
            "MasterLiveMusic": 20,
            "MasterMemberCard": 19,
            "MasterEvent": 0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            report = ContentValidator(
                object_store=FileObjectStore(Path(temporary)),
                max_critical_table_drop_ratio=0.5,
            ).validate(candidate, baseline=baseline)

        drops = [issue for issue in report.issues if issue.code == "critical_table_drop"]
        self.assertEqual(len(drops), 2)
        self.assertTrue(any(issue.code == "critical_table_empty" for issue in report.issues))

    def test_rejects_unresolved_relations_and_flattened_localized_text(self) -> None:
        candidate = _manifest([])
        candidate["availableTargets"] = ["asset:known"]
        candidate["references"] = [
            {"source": "card:1", "target": "asset:missing"},
        ]
        candidate["entities"] = [
            {"id": "song:1", "localizedText": "flattened title"},
            {"id": "event:1", "localizedText": {"ja": ""}},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            report = ContentValidator(
                object_store=FileObjectStore(Path(temporary))
            ).validate(candidate)

        codes = {issue.code for issue in report.issues}
        self.assertIn("reference_unresolved", codes)
        self.assertIn("localized_text_flattened", codes)
        self.assertIn("localized_text_empty", codes)

    def test_blocks_secret_output_private_responses_and_unapproved_remote_code(self) -> None:
        baseline = _manifest([])
        candidate = _manifest([])
        candidate["contentRelease"]["versionVector"]["remoteCodeHash"] = "b" * 64
        candidate["logs"] = [
            "Authorization: Bearer example-super-secret",
            "deviceId=private-device-value",
        ]
        candidate["privateResponse"] = {"body": "must-not-be-published"}
        with tempfile.TemporaryDirectory() as temporary:
            report = ContentValidator(
                object_store=FileObjectStore(Path(temporary))
            ).validate(candidate, baseline=baseline)

        codes = {issue.code for issue in report.issues}
        self.assertIn("output_secret_detected", codes)
        self.assertIn("private_response_detected", codes)
        self.assertIn("remote_code_review_required", codes)
        serialized = repr(report)
        self.assertNotIn("example-super-secret", serialized)
        self.assertNotIn("private-device-value", serialized)
        self.assertNotIn("must-not-be-published", serialized)

    def test_current_golden_release_passes_offline_validation(self) -> None:
        manifest_path = (
            REPO_ROOT
            / "data/releases/global/staging/global-staging-6521695fc2fd2dfc/manifest.json"
        )
        if not manifest_path.is_file():
            self.skipTest("Golden release objects are not present")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        report = ContentValidator(
            object_store=FileObjectStore(REPO_ROOT / "data")
        ).validate(manifest, baseline=manifest)

        self.assertTrue(report.valid, report.issues)

    def test_remote_code_approval_requires_hash_and_audit_evidence(self) -> None:
        baseline = _manifest([])
        candidate = _manifest([])
        remote_hash = "b" * 64
        candidate["contentRelease"]["versionVector"]["remoteCodeHash"] = remote_hash
        candidate["approvals"] = {
            "remoteCode": {
                "hash": remote_hash,
                "confirmedBy": "release-owner",
                "confirmedAt": "2026-07-18T14:30:00+08:00",
                "evidence": "manual review ticket RC-1",
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            report = ContentValidator(
                object_store=FileObjectStore(Path(temporary))
            ).validate(candidate, baseline=baseline)

        self.assertNotIn(
            "remote_code_review_required",
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
