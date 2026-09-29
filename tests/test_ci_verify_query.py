"""T6 tests for the Query Service integration in ``tools/ci_verify.sh``.

The script is the canonical local verification entry point. After T6 it
MUST additionally:
- provision (or reuse) a venv for the Query Service deps;
- run the seven Query Service test modules against that venv;
- build ``Dockerfile.query`` alongside the Worker image;
- run an offline container smoke that exercises ``/api/v1/health/live``
  and a fixture-only ``/api/v1/events`` call.

The script is exercised as text only — we do not shell out to docker or
pip from the test runner. Docker is an external gate.
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CI_VERIFY = REPO_ROOT / "tools" / "ci_verify.sh"
QUERY_TOOL = REPO_ROOT / "tools" / "query_capacity_check.py"


class CiVerifyQueryStepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CI_VERIFY.read_text(encoding="utf-8")

    def test_provisions_or_reuses_query_venv(self) -> None:
        self.assertIn("python3 -m venv --system-site-packages \"$QUERY_VENV\"", self.source)
        self.assertIn("requirements-query.txt", self.source)

    def test_provisions_query_dependencies_before_full_discovery(self) -> None:
        provision = self.source.index("provisioning query service venv")
        discovery = self.source.index("-m unittest discover -s tests -v")
        self.assertLess(provision, discovery)
        self.assertIn(
            '"$QUERY_VENV/bin/python" -m unittest discover -s tests -v',
            self.source,
        )

    def test_runs_query_service_test_modules(self) -> None:
        for module in (
            "tests.test_query_contracts",
            "tests.test_content_query_projection",
            "tests.test_dataset_query",
            "tests.test_query_http",
            "tests.test_identity_binding",
            "tests.test_identity_backup",
            "tests.test_query_delivery",
            "tests.test_query_capacity_check",
            "tests.test_nginx_contract",
        ):
            self.assertIn(
                module,
                self.source,
                msg=f"ci_verify.sh must run {module}",
            )

    def test_builds_query_image(self) -> None:
        self.assertIn("docker build --file Dockerfile.query", self.source)
        self.assertIn("--build-arg PYTHON_BASE_IMAGE=", self.source)
        self.assertIn("--build-arg NODE_BASE_IMAGE=", self.source)
        self.assertIn("QUERY_IMAGE", self.source)
        # The query smoke container MUST publish only to loopback.
        self.assertIn("127.0.0.1:18090:8090", self.source)

    def test_query_smoke_only_uses_fixture_data(self) -> None:
        # The smoke must hit ``/api/v1/health/live`` and a fixture-only
        # ``/api/v1/events`` call. The readiness endpoint is allowed to
        # be 503 because the smoke data root has no published releases.
        self.assertIn("/api/v1/health/live", self.source)
        self.assertIn("/api/v1/health/ready", self.source)
        self.assertIn("/api/v1/events", self.source)
        self.assertIn("httpx.Client(base_url=base", self.source)
        self.assertIn("python3 -m backend.identity_backup", self.source)
        self.assertIn("identity-latest.sqlite3", self.source)
        # Must not mention a real upstream game host.
        for forbidden in ("real_host",):
            self.assertNotIn(forbidden, self.source.lower())

    def test_capacity_tool_is_documented(self) -> None:
        self.assertTrue(QUERY_TOOL.is_file())
        self.assertIn("query_capacity_check", self.source)


if __name__ == "__main__":
    unittest.main()
