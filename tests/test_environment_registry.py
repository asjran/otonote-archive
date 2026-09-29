from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.environment_registry import EnvironmentRegistry  # noqa: E402
from tools.resource_pipeline.cli import main  # noqa: E402


class EnvironmentRegistryTest(unittest.TestCase):
    def test_repository_declares_only_disabled_global_targets(self) -> None:
        registry = EnvironmentRegistry.load(REPO_ROOT / "config/environments")

        targets = {
            environment.environment_id: environment
            for environment in registry.environments
            if environment.environment_id in {
                "global-staging",
                "global-production",
            }
        }

        self.assertEqual(
            tuple(sorted(targets)),
            (
                "global-production",
                "global-staging",
            ),
        )
        self.assertTrue(all(not item.enabled for item in targets.values()))
        self.assertEqual(targets["global-staging"].activation_state, "external_gate")

    def test_rejects_auth_profile_reuse_across_server_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for environment_id, channel in (
                ("global-production", "production"),
                ("global-staging", "staging"),
            ):
                (root / f"{environment_id}.toml").write_text(
                    f'''environmentId = "{environment_id}"
region = "global"
channel = "{channel}"
enabled = false
clientBuildRef = "global-{channel}-pending-client-build"
clientGeneration = "pending-v1"
adapter = "protocol_pending"
allowedHosts = ["offline.invalid"]
authProfileRef = "shared-auth"
pollIntervalSeconds = 900
''',
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                ValueError,
                "authProfileRef cannot be shared",
            ):
                EnvironmentRegistry.load(root)

    def test_cli_lists_sync_targets_without_secret_references(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "environments",
                    "--config-root",
                    str(REPO_ROOT / "config/environments"),
                ]
            )

        report = json.loads(output.getvalue())
        targets = {
            item["environmentId"]: item
            for item in report["environments"]
            if item["environmentId"] in {
                "global-staging",
                "global-production",
            }
        }
        self.assertEqual(exit_code, 0)
        self.assertEqual(targets["global-staging"]["status"], "external_gate")
        self.assertEqual(
            targets["global-staging"]["gateReason"],
            "global_remote_protocol_unverified",
        )
        self.assertTrue(all(not item["enabled"] for item in targets.values()))
        self.assertNotIn("authProfileRef", output.getvalue())


if __name__ == "__main__":
    unittest.main()
