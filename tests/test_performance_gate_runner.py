from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tools/run_performance_gate.sh"


class PerformanceGateRunnerTest(unittest.TestCase):
    def test_missing_frozen_baseline_fails_closed_before_server_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            dist.mkdir()
            result = subprocess.run(
                [
                    "bash",
                    str(RUNNER),
                    "--dist",
                    str(dist),
                    "--baseline",
                    str(root / "missing-baseline.json"),
                    "--runner",
                    "fixture-runner",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("frozen browser baseline is missing", result.stderr)

    def test_runs_browser_and_complete_curve_against_an_isolated_loopback_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            for relative in (
                "global/zh-CN",
                "global/zh-CN/tools",
                "global/zh-CN/cards",
                "global/zh-CN/characters",
                "global/zh-CN/music",
                "global/zh-CN/events",
            ):
                target = dist / relative
                target.mkdir(parents=True)
                (target / "index.html").write_text("ok", encoding="utf-8")
            baseline = root / "baseline.json"
            baseline.write_text('{"schemaVersion": 1}\n', encoding="utf-8")
            browser_output = root / "browser.json"
            curve_output = root / "curve.json"
            browser_invocation = root / "browser-invocation.json"
            fake_node = root / "fake-node"
            fake_node.write_text(
                """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
if args[0].endswith("browser_regression.cjs"):
    pathlib.Path(os.environ["BROWSER_OUTPUT"]).write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    raise SystemExit(0)
output = pathlib.Path(args[args.index("--output") + 1])
output.write_text(json.dumps({"status": "fixture"}), encoding="utf-8")
pathlib.Path(os.environ["PERF_TEST_RECORD"]).write_text(json.dumps({
    "baseUrl": os.environ["PERF_BASE_URL"],
    "runner": os.environ["PERF_RUNNER"],
    "args": args,
}), encoding="utf-8")
""",
                encoding="utf-8",
            )
            fake_node.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "PERF_NODE_BIN": str(fake_node),
                    "PERF_TEST_RECORD": str(browser_invocation),
                }
            )

            result = subprocess.run(
                [
                    "bash",
                    str(RUNNER),
                    "--dist",
                    str(dist),
                    "--contract",
                    str(REPO_ROOT / "config/performance/gates.product-v1.json"),
                    "--baseline",
                    str(baseline),
                    "--browser-output",
                    str(browser_output),
                    "--curve-output",
                    str(curve_output),
                    "--runner",
                    "fixture-runner",
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            invocation = json.loads(browser_invocation.read_text(encoding="utf-8"))
            self.assertEqual(invocation["runner"], "fixture-runner")
            self.assertTrue(invocation["baseUrl"].startswith("http://127.0.0.1:"))
            self.assertIn("--budget-only", invocation["args"])
            self.assertEqual(
                invocation["args"][invocation["args"].index("--baseline") + 1],
                str(baseline),
            )
            curve = json.loads(curve_output.read_text(encoding="utf-8"))
            self.assertTrue(curve["pass"])
            self.assertEqual(
                [stage["concurrency"] for stage in curve["stages"]],
                [5, 10, 20, 50],
            )
            self.assertEqual(curve["routeSummary"]["method"], "GET")
            with self.assertRaises((OSError, urllib.error.URLError)):
                urllib.request.urlopen(invocation["baseUrl"], timeout=0.2)

    def test_browser_hard_failure_stops_the_curve_and_still_cleans_the_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("ok", encoding="utf-8")
            baseline = root / "baseline.json"
            baseline.write_text('{"schemaVersion": 1}\n', encoding="utf-8")
            browser_output = root / "browser.json"
            curve_output = root / "curve.json"
            base_url_record = root / "base-url.txt"
            fake_node = root / "failing-node"
            fake_node.write_text(
                """#!/usr/bin/env python3
import os
import pathlib
import json
import sys

if sys.argv[1].endswith("browser_regression.cjs"):
    pathlib.Path(os.environ["BROWSER_OUTPUT"]).write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    raise SystemExit(0)

pathlib.Path(os.environ["PERF_TEST_RECORD"]).write_text(
    os.environ["PERF_BASE_URL"],
    encoding="utf-8",
)
raise SystemExit(7)
""",
                encoding="utf-8",
            )
            fake_node.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "PERF_NODE_BIN": str(fake_node),
                    "PERF_TEST_RECORD": str(base_url_record),
                }
            )

            result = subprocess.run(
                [
                    "bash",
                    str(RUNNER),
                    "--dist",
                    str(dist),
                    "--baseline",
                    str(baseline),
                    "--browser-output",
                    str(browser_output),
                    "--curve-output",
                    str(curve_output),
                    "--runner",
                    "fixture-runner",
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 7)
            self.assertFalse(curve_output.exists())
            base_url = base_url_record.read_text(encoding="utf-8")
            with self.assertRaises((OSError, urllib.error.URLError)):
                urllib.request.urlopen(base_url, timeout=0.2)


if __name__ == "__main__":
    unittest.main()
