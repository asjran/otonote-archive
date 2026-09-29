from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CiContractTest(unittest.TestCase):
    def test_worker_container_consumes_prebuilt_projection_inputs(self) -> None:
        source = (REPO_ROOT / "tools/ci_verify.sh").read_text(encoding="utf-8")
        container_branch = source.split(
            'CI_EVIDENCE_MODE="local-runtime"\nelse',
            maxsplit=1,
        )[1].split('CI_EVIDENCE_MODE="worker-container"', maxsplit=1)[0]

        self.assertEqual(source.count("npm run catalog:preflight"), 1)
        self.assertNotIn("npm run catalog:preflight", container_branch)
        self.assertNotIn("release_build.py", container_branch)
        self.assertNotIn("perf:budget", container_branch)
        self.assertNotIn("test_browser_regression.py", container_branch)
        self.assertIn("python3 -m tools.site_artifact build", source)
        self.assertIn("python3 -m tools.site_artifact verify", source)
        self.assertIn('--artifact-root "$CI_DIST"', source)
        self.assertIn(
            "python3 tools/docs_status.py",
            source,
        )
        self.assertIn(
            "python3 -m tools.artifact_registry",
            source,
        )

    def test_local_runtime_binds_fresh_performance_reports_into_ci_evidence(self) -> None:
        source = (REPO_ROOT / "tools/ci_verify.sh").read_text(encoding="utf-8")
        local_branch = source.split(
            'if [[ "${OURNOTES_SKIP_DOCKER_BUILD:-0}" == "1" ]]; then',
            maxsplit=1,
        )[1].split('CI_EVIDENCE_MODE="local-runtime"\nelse', maxsplit=1)[0]
        container_branch = source.split(
            'CI_EVIDENCE_MODE="local-runtime"\nelse',
            maxsplit=1,
        )[1].split('CI_EVIDENCE_MODE="worker-container"', maxsplit=1)[0]

        self.assertIn('PERFORMANCE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"', local_branch)
        self.assertIn('"$REPO_ROOT/tools/run_performance_gate.sh"', local_branch)
        self.assertIn("tools/browser_regression.cjs", (
            REPO_ROOT / "tools/run_performance_gate.sh"
        ).read_text(encoding="utf-8"))
        self.assertNotIn("run_performance_gate.sh", container_branch)
        for argument in (
            "--performance-contract",
            "--performance-baseline",
            "--browser-performance-report",
            "--load-curve-report",
            "--performance-not-before",
        ):
            self.assertIn(argument, source)


if __name__ == "__main__":
    unittest.main()
