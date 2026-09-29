from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.artifact_registry import schema_versions  # noqa: E402
from tools.performance_contract import load_performance_contract  # noqa: E402
from tools.site_artifact import build_artifact  # noqa: E402


class CiEvidenceTest(unittest.TestCase):
    def test_local_runtime_with_partial_performance_inputs_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ci.json"
            output.write_text('{"status": "passed"}\n', encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    "tools/ci_evidence.py",
                    "--mode",
                    "local-runtime",
                    "--artifact-root",
                    temporary,
                    "--performance-contract",
                    str(REPO_ROOT / "config/performance/gates.product-v1.json"),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("performance evidence must be provided as a complete set", result.stderr)
            self.assertFalse(output.exists())

    def test_records_only_a_passed_complete_ci_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            output = temporary_root / "ci.json"
            artifact_root = temporary_root / "dist"
            artifact_root.mkdir()
            (artifact_root / "index.html").write_text("ok", encoding="utf-8")
            data_root = artifact_root / "data"
            data_root.mkdir()
            media_index = data_root / "media-index.json"
            media_index.write_text(
                '{"schemaVersion": 1, "records": []}\n',
                encoding="utf-8",
            )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            schemas = schema_versions()
            schemas["media-index.json"] = 1
            build_artifact(
                artifact_root=artifact_root,
                release_index=(
                    REPO_ROOT
                    / "site/src/data/generated/release-index.json"
                ),
                package_lock=REPO_ROOT / "site/package-lock.json",
                media_index=media_index,
                schemas=schemas,
                site_release_id="ci-test",
                git_commit=revision,
                docker_image="ci:test",
                built_at="2026-07-26T12:00:00Z",
            )
            contract_path = REPO_ROOT / "config/performance/gates.product-v1.json"
            contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
            contract_digest = "sha256:" + hashlib.sha256(
                json.dumps(
                    contract_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            contract = load_performance_contract(contract_path)
            case_ids = [case.id for case in contract.browser_cases]
            baseline = temporary_root / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "generatedAt": "2026-08-12T00:00:00Z",
                        "gitHead": revision,
                        "contractDigest": contract_digest,
                        "runner": "fixture-runner",
                        "cases": [
                            {"id": case_id, "bytes": 100, "requestCount": 1}
                            for case_id in case_ids
                        ],
                    }
                ),
                encoding="utf-8",
            )
            browser_report = temporary_root / "browser.json"
            browser_report.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "generatedAt": "2026-08-13T00:00:01Z",
                        "gitHead": revision,
                        "contractDigest": contract_digest,
                        "runner": "fixture-runner",
                        "baseline": str(baseline),
                        "writeBaseline": False,
                        "budgetOnly": True,
                        "results": [
                            {"id": case_id, "pass": True} for case_id in case_ids
                        ],
                    }
                ),
                encoding="utf-8",
            )
            curve_report = temporary_root / "curve.json"
            curve_report.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "startedAt": "2026-08-13T00:00:02Z",
                        "gitHead": revision,
                        "contractDigest": contract_digest,
                        "server": "fixture-server",
                        "warmupRequests": 6,
                        "routeSummary": {
                            "method": "GET",
                            "count": 6,
                            "paths": list(contract.load_paths),
                        },
                        "pass": True,
                        "stages": [
                            {
                                "concurrency": concurrency,
                                "requests": requests,
                                "hardGate": hard_gate,
                                "gate": "hard_passed" if hard_gate else "observed",
                            }
                            for concurrency, requests, hard_gate in (
                                (5, 100, True),
                                (10, 200, True),
                                (20, 200, False),
                                (50, 100, False),
                            )
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    "tools/ci_evidence.py",
                    "--mode",
                    "local-runtime",
                    "--output",
                    str(output),
                    "--artifact-root",
                    str(artifact_root),
                    "--performance-contract",
                    str(contract_path),
                    "--performance-baseline",
                    str(baseline),
                    "--browser-performance-report",
                    str(browser_report),
                    "--load-curve-report",
                    str(curve_report),
                    "--performance-not-before",
                    "2026-08-13T00:00:00Z",
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["mode"], "local-runtime")
            self.assertEqual(len(payload["revision"]), 40)
            self.assertTrue(payload["contentReleases"])
            self.assertEqual(len(payload["packageLockSha256"]), 64)
            self.assertEqual(payload["schemaVersions"]["catalog.json"], 6)
            self.assertEqual(len(payload["releaseIndexSha256"]), 64)
            self.assertEqual(payload["sitePerformance"]["head"], revision)
            self.assertEqual(
                payload["sitePerformance"]["contract"]["digest"],
                contract_digest,
            )
            self.assertEqual(
                payload["sitePerformance"]["baseline"]["sha256"],
                hashlib.sha256(baseline.read_bytes()).hexdigest(),
            )
            self.assertEqual(payload["sitePerformance"]["browser"]["caseCount"], 36)
            self.assertEqual(
                payload["sitePerformance"]["loadCurve"]["stageConcurrencies"],
                [5, 10, 20, 50],
            )
            self.assertEqual(
                payload["checks"],
                [
                    "docs-status",
                    "artifact-schema-registry",
                    "python-unittest-discovery",
                    "node-test",
                    "astro-check",
                    "site-matrix-build",
                    "site-artifact-verify",
                    "build-performance-budget",
                    "site-performance-gate",
                ],
            )

    def test_worker_evidence_does_not_claim_a_site_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ci.json"
            subprocess.run(
                [
                    "python3",
                    "tools/ci_evidence.py",
                    "--mode",
                    "worker-container",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(
                payload["checks"],
                [
                    "docs-status",
                    "artifact-schema-registry",
                    "python-unittest-discovery",
                    "worker-runtime",
                    "resource-pipeline-smoke",
                ],
            )
            self.assertNotIn("sitePerformance", payload)


if __name__ == "__main__":
    unittest.main()
