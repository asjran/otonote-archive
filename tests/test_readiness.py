from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.readiness import build_readiness_report, render_markdown  # noqa: E402


class ReadinessReportTest(unittest.TestCase):
    def _write_json(self, root: Path, relative: str, value: object) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_reports_current_catalog_gaps_and_external_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_json(
                root,
                "catalog/site-data/build-report.json",
                {
                    "generatedAt": "2026-07-22T00:00:00+00:00",
                    "musicChartCount": 132,
                    "pendingAssetCount": 88,
                    "missingSkillIconCount": 31,
                    "warnings": [
                        "music-chart-1: parsed judgement count 1 differs from official Full Combo 2",
                        "music-chart-2: parsed judgement count 3 differs from official Full Combo 4",
                        "unrelated warning",
                    ],
                    "validationErrors": [],
                },
            )

            report = build_readiness_report(
                root,
                now=datetime(2026, 7, 22, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(report["metrics"]["musicChartCount"], 132)
            self.assertEqual(report["metrics"]["warningCount"], 3)
            self.assertEqual(report["metrics"]["fullComboMismatchCount"], 2)
            self.assertEqual(report["metrics"]["pendingAssetCount"], 88)
            self.assertEqual(report["metrics"]["missingSkillIconCount"], 31)
            self.assertEqual(report["tasks"]["T2"]["status"], "failed")
            self.assertEqual(report["tasks"]["T3"]["status"], "failed")
            self.assertEqual(report["tasks"]["B"]["status"], "external_gate")
            self.assertEqual(report["tasks"]["E0"]["status"], "external_gate")
            self.assertEqual(report["tasks"]["C"]["status"], "excluded")

    def test_global_offline_intake_passes_without_closing_remote_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input/global/apks").mkdir(parents=True)
            self._write_json(root, "output/readiness/global-intake.json", {
                "status": "passed",
                "sourceStatus": "offline_package",
                "remoteValidation": "external_gate",
                "remoteValidated": False,
                "activationAttempted": False,
                "autoPublish": False,
                "projections": {locale: locale for locale in ("zh-CN", "zh-TW", "en", "ja")},
            })
            report = build_readiness_report(root)
            self.assertEqual(report["tasks"]["E0"]["status"], "passed")
            self.assertEqual(report["tasks"]["B"]["status"], "external_gate")
            self.assertIn("global_remote_protocol_unverified", report["tasks"]["B"]["reasons"])

    def test_marks_catalog_report_stale_and_does_not_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_json(
                root,
                "catalog/site-data/build-report.json",
                {
                    "generatedAt": "2026-07-01T00:00:00Z",
                    "musicChartCount": 132,
                    "pendingAssetCount": 0,
                    "missingSkillIconCount": 0,
                    "unexplainedPendingAssetCount": 0,
                    "unexplainedMissingSkillIconCount": 0,
                    "warnings": [],
                    "validationErrors": [],
                },
            )

            report = build_readiness_report(
                root,
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
                max_age_hours=48,
            )

            self.assertFalse(report["inputs"]["catalogBuildReport"]["fresh"])
            self.assertEqual(report["tasks"]["T2"]["status"], "failed")
            self.assertIn("stale", report["tasks"]["T2"]["reasons"])

    def test_o1_fails_when_local_performance_head_does_not_match_ci_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = "a" * 64
            self._write_json(
                root,
                "output/readiness/ci.json",
                {
                    "status": "passed",
                    "generatedAt": "2026-08-13T00:00:00+00:00",
                    "mode": "local-runtime",
                    "revision": "head-a",
                    "sitePerformance": {
                        "status": "passed",
                        "head": "head-b",
                        "contract": {"digest": f"sha256:{digest}"},
                        "baseline": {"sha256": digest},
                        "browser": {"sha256": digest},
                        "loadCurve": {"sha256": digest},
                    },
                },
            )
            self._write_json(
                root,
                "output/readiness/production-performance.json",
                {"status": "passed", "reasonCodes": []},
            )

            report = build_readiness_report(
                root,
                now=datetime(2026, 8, 13, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(report["tasks"]["O1"]["status"], "failed")
        self.assertIn(
            "o1_local_performance_evidence_missing_or_failed",
            report["tasks"]["O1"]["reasons"],
        )

    def test_complete_evidence_closes_current_scope_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated_at = "2026-07-22T00:00:00+00:00"
            self._write_json(
                root,
                "catalog/site-data/build-report.json",
                {
                    "generatedAt": generated_at,
                    "musicChartCount": 132,
                    "pendingAssetCount": 0,
                    "missingSkillIconCount": 0,
                    "unexplainedPendingAssetCount": 0,
                    "unexplainedMissingSkillIconCount": 0,
                    "warnings": [],
                    "validationErrors": [],
                },
            )
            self._write_json(root, "output/readiness/package-diff.json", {"status": "passed"})
            self._write_json(root, "output/readiness/database-shards.json", {"status": "passed"})
            self._write_json(root, "output/readiness/media-index.json", {"status": "passed"})
            self._write_json(root, "output/readiness/monitor.json", {"status": "passed"})
            self._write_json(root, "output/readiness/shadow-rehearsal.json", {"status": "passed"})
            self._write_json(
                root,
                "output/readiness/ci.json",
                {
                    "status": "passed",
                    "generatedAt": generated_at,
                    "mode": "local-runtime",
                    "revision": "fixture-head",
                    "sitePerformance": {
                        "status": "passed",
                        "head": "fixture-head",
                        "contract": {"digest": f"sha256:{'a' * 64}"},
                        "baseline": {"sha256": "b" * 64},
                        "browser": {"sha256": "c" * 64},
                        "loadCurve": {"sha256": "d" * 64},
                    },
                },
            )
            self._write_json(root, "output/readiness/browser-regression.json", {
                "status": "passed",
                "generatedAt": generated_at,
                "gitHead": "fixture-head",
            })
            self._write_json(
                root,
                "output/readiness/production-performance.json",
                {
                    "status": "external_gate",
                    "reasonCodes": ["monitor_complete_days_insufficient"],
                },
            )

            report = build_readiness_report(
                root,
                now=datetime(2026, 7, 22, 1, tzinfo=timezone.utc),
            )

            for task in ("T1", "T2", "T3", "T4", "T5", "A1", "A2", "A3", "A4"):
                self.assertEqual(report["tasks"][task]["status"], "passed")
            self.assertEqual(report["tasks"]["O1"]["status"], "external_gate")
            self.assertIn("O1", report["summary"]["externalGates"])
            self.assertEqual(report["summary"]["status"], "external_gate")
            self.assertEqual(report["tasks"]["B"]["status"], "external_gate")
            self.assertEqual(report["tasks"]["C"]["status"], "excluded")

            markdown = render_markdown(report)
            self.assertIn("T1", markdown)
            self.assertIn("external_gate", markdown)
            self.assertIn("Full Combo", markdown)

    def test_o1_passes_only_when_local_and_production_evidence_both_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_json(
                root,
                "output/readiness/ci.json",
                {
                    "status": "passed",
                    "generatedAt": "2026-08-13T00:00:00+00:00",
                    "mode": "local-runtime",
                    "revision": "fixture-head",
                    "sitePerformance": {
                        "status": "passed",
                        "head": "fixture-head",
                        "contract": {"digest": f"sha256:{'a' * 64}"},
                        "baseline": {"sha256": "b" * 64},
                        "browser": {"sha256": "c" * 64},
                        "loadCurve": {"sha256": "d" * 64},
                    },
                },
            )
            self._write_json(
                root,
                "output/readiness/production-performance.json",
                {
                    "status": "passed",
                    "reasonCodes": [],
                    "generatedAt": "2026-08-13T00:00:00+00:00",
                },
            )

            report = build_readiness_report(
                root,
                now=datetime(2026, 8, 13, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(report["tasks"]["O1"]["status"], "passed")
        self.assertNotIn("O1", report["summary"]["externalGates"])
        self.assertIn("B", report["summary"]["externalGates"])

    def test_o1_does_not_accept_stale_or_unversioned_production_evidence(self) -> None:
        for generated_at in (None, "2026-08-01T00:00:00+00:00"):
            with self.subTest(generated_at=generated_at), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                production = {"status": "passed", "reasonCodes": []}
                if generated_at is not None:
                    production["generatedAt"] = generated_at
                self._write_json(root, "output/readiness/production-performance.json", production)
                self._write_json(root, "output/readiness/ci.json", {
                    "status": "passed", "generatedAt": "2026-08-13T00:00:00+00:00",
                    "mode": "local-runtime", "revision": "head",
                    "sitePerformance": {
                        "status": "passed", "head": "head",
                        "contract": {"digest": f"sha256:{'a' * 64}"},
                        "baseline": {"sha256": "b" * 64},
                        "browser": {"sha256": "c" * 64},
                        "loadCurve": {"sha256": "d" * 64},
                    },
                })

                report = build_readiness_report(
                    root,
                    now=datetime(2026, 8, 13, tzinfo=timezone.utc),
                )

            self.assertEqual(report["tasks"]["O1"]["status"], "external_gate")
            self.assertIn(
                "production_performance_evidence_stale_or_unversioned",
                report["tasks"]["O1"]["reasons"],
            )

    def test_t5_rejects_a_fresh_browser_report_from_another_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_json(root, "output/readiness/ci.json", {
                "status": "passed",
                "generatedAt": "2026-08-13T00:00:00+00:00",
                "revision": "head-a",
            })
            self._write_json(root, "output/readiness/browser-regression.json", {
                "status": "passed",
                "generatedAt": "2026-08-13T00:05:00+00:00",
                "gitHead": "head-b",
            })

            report = build_readiness_report(
                root,
                now=datetime(2026, 8, 13, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(report["tasks"]["T5"]["status"], "failed")

    def test_t5_rejects_fresh_evidence_from_the_previous_repository_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_json(root, "output/readiness/ci.json", {
                "status": "passed",
                "generatedAt": "2026-08-13T00:00:00+00:00",
                "revision": "previous-head",
            })
            self._write_json(root, "output/readiness/browser-regression.json", {
                "status": "passed",
                "generatedAt": "2026-08-13T00:05:00+00:00",
                "gitHead": "previous-head",
            })

            report = build_readiness_report(
                root,
                now=datetime(2026, 8, 13, 1, tzinfo=timezone.utc),
                expected_revision="current-head",
            )

        self.assertEqual(report["tasks"]["T5"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
