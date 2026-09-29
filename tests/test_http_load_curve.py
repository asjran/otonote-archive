from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path

from tools.http_load import run_load
from tools.http_load_curve import load_curve_contract, run_curve


REPO_ROOT = Path(__file__).resolve().parents[1]


class HttpLoadCurveTest(unittest.TestCase):
    def test_contract_curve_keeps_warmup_out_of_measurements_and_only_hard_stages_block(self) -> None:
        fetched_urls: list[str] = []

        def fetch_fixture(url: str, timeout: float) -> dict[str, object]:
            fetched_urls.append(url)
            return {
                "url": url,
                "status": 200,
                "bytes": 12,
                "ttfbMs": 10.0,
                "totalMs": 20.0,
                "elapsedMs": 20.0,
                "error": None,
            }

        single_stage = run_load(
            base_url="http://fixture.invalid",
            paths=["/one", "/two"],
            concurrency=2,
            requests=2,
            timeout=1,
            warmup_requests=6,
            fetcher=fetch_fixture,
        )

        self.assertEqual(len(fetched_urls), 8)
        self.assertEqual(single_stage["summary"]["requests"], 2)
        self.assertEqual(len(single_stage["results"]), 2)
        self.assertEqual(
            single_stage["summary"]["ttfbMs"],
            {"p50": 10.0, "p95": 10.0, "p99": 10.0, "max": 10.0},
        )
        self.assertEqual(
            single_stage["summary"]["totalMs"],
            {"p50": 20.0, "p95": 20.0, "p99": 20.0, "max": 20.0},
        )

        contract, contract_digest = load_curve_contract(
            REPO_ROOT / "config/performance/gates.product-v1.json"
        )
        calls: list[tuple[int, int, int, tuple[str, ...]]] = []

        def observational_failure_stage(**kwargs: object) -> dict[str, object]:
            concurrency = int(kwargs["concurrency"])
            requests = int(kwargs["requests"])
            calls.append(
                (
                    concurrency,
                    requests,
                    int(kwargs["warmup_requests"]),
                    tuple(str(value) for value in kwargs["paths"]),
                )
            )
            failures = 1 if concurrency in {20, 50} else 0
            return {
                "summary": {
                    "concurrency": concurrency,
                    "requests": requests,
                    "durationSeconds": 2.0,
                    "requestsPerSecond": float(concurrency * 10),
                    "failures": failures,
                    "errorRate": failures / requests,
                    "ttfbMs": {"p50": 10.0, "p95": 20.0, "p99": 30.0, "max": 40.0},
                    "totalMs": {"p50": 20.0, "p95": 40.0, "p99": 60.0, "max": 80.0},
                },
                "results": [],
            }

        metadata = {
            "startedAt": "2026-08-12T00:00:00Z",
            "gitHead": "fixture-head",
            "environment": {"platform": "fixture-os", "cpuCount": 2},
            "server": "fixture-server",
        }
        report = run_curve(
            base_url="http://fixture.invalid",
            contract=contract,
            contract_digest=contract_digest,
            timeout=1,
            stage_runner=observational_failure_stage,
            metadata=metadata,
        )

        self.assertEqual(
            [(value[0], value[1], value[2]) for value in calls],
            [(5, 100, 6), (10, 200, 6), (20, 200, 6), (50, 100, 6)],
        )
        self.assertTrue(all(value[3] == contract.load_paths for value in calls))
        self.assertTrue(report["pass"])
        self.assertEqual(report["gitHead"], "fixture-head")
        self.assertEqual(report["environment"], {"platform": "fixture-os", "cpuCount": 2})
        self.assertEqual(report["server"], "fixture-server")
        self.assertEqual(report["contractDigest"], contract_digest)
        self.assertEqual(
            report["routeSummary"],
            {"method": "GET", "count": 6, "paths": list(contract.load_paths)},
        )
        self.assertEqual(report["stages"][0]["gate"], "hard_passed")
        self.assertEqual(report["stages"][1]["gate"], "hard_passed")
        self.assertEqual(report["stages"][2]["gate"], "observed_with_errors")
        self.assertEqual(report["stages"][3]["gate"], "observed_with_errors")
        self.assertEqual(report["stages"][2]["summary"]["ttfbMs"]["p95"], 20.0)
        self.assertEqual(report["stages"][2]["summary"]["totalMs"]["p95"], 40.0)
        self.assertIn("relativeToConcurrency10", report["stages"][2])

        def hard_failure_stage(**kwargs: object) -> dict[str, object]:
            result = observational_failure_stage(**kwargs)
            if int(kwargs["concurrency"]) == 10:
                result["summary"]["failures"] = 1
                result["summary"]["errorRate"] = 1 / int(kwargs["requests"])
            return result

        blocked = run_curve(
            base_url="http://fixture.invalid",
            contract=contract,
            contract_digest=contract_digest,
            timeout=1,
            stage_runner=hard_failure_stage,
            metadata=metadata,
        )
        self.assertFalse(blocked["pass"])
        self.assertEqual(blocked["stages"][1]["gate"], "hard_failed")

    def test_curve_cli_supports_direct_script_execution(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools/http_load_curve.py"), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--contract", result.stdout)


if __name__ == "__main__":
    unittest.main()
