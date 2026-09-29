from __future__ import annotations

import sys
import json
import tempfile
import contextlib
import io
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.environment_registry import EnvironmentRegistry  # noqa: E402
from tools.resource_pipeline.source_adapter import ReplaySourceAdapter  # noqa: E402
from tools.resource_pipeline.source_adapter import ReplayPipelineAdapter  # noqa: E402
from tools.resource_pipeline.pipeline import ContentPipeline  # noqa: E402
from tools.resource_pipeline.models import JobStatus  # noqa: E402
from tools.resource_pipeline.cli import main  # noqa: E402


FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/resource_pipeline/source-replay"


class ReplaySourceAdapterTest(unittest.TestCase):

    def test_rejects_catalog_or_master_from_another_release(self) -> None:
        registry = EnvironmentRegistry.load(REPO_ROOT / "config/environments")
        value = json.loads(
            (FIXTURE_ROOT / "global-staging-hot-update.json").read_text(
                encoding="utf-8"
            )
        )
        value["catalog"]["catalogHash"] = "cross-release-catalog"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cross-release.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Catalog version mismatch"):
                ReplaySourceAdapter.from_fixture(
                    path,
                    environment=registry.get("global-staging"),
                )

    def test_global_replay_runs_the_recoverable_pipeline_without_network(self) -> None:
        registry = EnvironmentRegistry.load(REPO_ROOT / "config/environments")
        source = ReplaySourceAdapter.from_fixture(
            FIXTURE_ROOT / "global-staging-hot-update.json",
            environment=registry.get("global-staging"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = ContentPipeline(
                data_root=Path(temporary),
                adapter_version="source-replay-v1",
                input_fingerprint="b" * 64,
            ).run(
                job_id="global-replay-v2",
                environment_id="global-staging",
                content_release_ref="global-staging-fixture-v2",
                adapter=ReplayPipelineAdapter(source),
            )

        self.assertEqual(result.checkpoint.status, JobStatus.READY_FOR_PUBLISH)
        self.assertEqual(
            result.artifacts["sourceEvidence"]["serverIdentity"],
            "global/staging",
        )
        self.assertEqual(
            result.artifacts["assetPlan"][0]["primaryKey"],
            "global-new-bundle",
        )

    def test_cli_replay_uses_the_same_recoverable_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "replay-source",
                        "--environment",
                        "global-staging",
                        "--fixture",
                        str(FIXTURE_ROOT / "global-staging-hot-update.json"),
                        "--job-id",
                        "global-cli-replay",
                        "--data-root",
                        temporary,
                    ]
                )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "ready_for_publish")
        self.assertEqual(report["environmentId"], "global-staging")
        self.assertEqual(report["sourceStatus"], "offline_replay")


if __name__ == "__main__":
    unittest.main()
