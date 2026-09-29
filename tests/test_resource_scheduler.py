from __future__ import annotations

import contextlib
import fcntl
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.cli import main  # noqa: E402
from tools.resource_pipeline.models import VersionVector  # noqa: E402
from tools.resource_pipeline.scheduler import EnvironmentScheduler  # noqa: E402


def write_environment(
    root: Path,
    environment_id: str,
    *,
    region: str,
    channel: str,
    enabled: bool,
) -> None:
    (root / f"{environment_id}.toml").write_text(
        f'''environmentId = "{environment_id}"
region = "{region}"
channel = "{channel}"
enabled = {str(enabled).lower()}
clientBuildRef = "{region}-{channel}-android-1-aaaaaaaaaaaaaaaa"
clientGeneration = "fixture-v1"
adapter = "protocol_pending"
allowedHosts = ["offline.invalid"]
authProfileRef = "{environment_id}-auth"
pollIntervalSeconds = 900
''',
        encoding="utf-8",
    )


class EnvironmentSchedulerTest(unittest.TestCase):
    def test_worker_rejects_cross_channel_auth_profile_reuse_before_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "environments"
            config_root.mkdir()
            write_environment(
                config_root,
                "global-production",
                region="global",
                channel="production",
                enabled=False,
            )
            write_environment(
                config_root,
                "global-staging",
                region="global",
                channel="staging",
                enabled=False,
            )
            for path in config_root.glob("*.toml"):
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        f'{path.stem}-auth',
                        "shared-auth",
                    ),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                ValueError,
                "authProfileRef cannot be shared",
            ):
                main(
                    [
                        "run",
                        "--all-enabled",
                        "--config-root",
                        str(config_root),
                        "--data-root",
                        str(root / "data"),
                    ]
                )

    def test_one_environment_failure_does_not_block_other_enabled_regions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "environments"
            config_root.mkdir()
            write_environment(
                config_root,
                "global-production",
                region="global",
                channel="production",
                enabled=True,
            )
            write_environment(
                config_root,
                "global-staging",
                region="global",
                channel="staging",
                enabled=True,
            )
            write_environment(
                config_root,
                "jp-disabled",
                region="global",
                channel="production",
                enabled=False,
            )
            calls: list[str] = []

            def run_environment(environment):
                calls.append(environment.environment_id)
                if environment.environment_id == "global-staging":
                    raise RuntimeError("authentication expired")
                return "unchanged"

            report = EnvironmentScheduler(
                config_root=config_root,
                data_root=root / "data",
            ).run(run_environment)

            self.assertEqual(calls, ["global-production", "global-staging"])
            self.assertEqual(
                [(item.environment_id, item.status) for item in report.results],
                [
                    ("global-production", "unchanged"),
                    ("global-staging", "failed"),
                ],
            )
            self.assertNotIn("jp-disabled", calls)

    def test_locked_environment_is_skipped_without_invoking_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "environments"
            config_root.mkdir()
            write_environment(
                config_root,
                "global-staging",
                region="global",
                channel="staging",
                enabled=True,
            )
            lock_root = root / "data" / "locks"
            lock_root.mkdir(parents=True)
            with (lock_root / "global-staging.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                report = EnvironmentScheduler(
                    config_root=config_root,
                    data_root=root / "data",
                ).run(lambda environment: self.fail("locked runner was invoked"))

            self.assertEqual(
                [(item.environment_id, item.status) for item in report.results],
                [("global-staging", "locked")],
            )

    def test_all_enabled_command_with_no_enabled_environments_is_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "environments"
            config_root.mkdir()
            write_environment(
                config_root,
                "global-staging",
                region="global",
                channel="staging",
                enabled=False,
            )
            data_root = root / "data"

            outputs: list[dict[str, object]] = []
            for _ in range(2):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = main(
                        [
                            "run",
                            "--all-enabled",
                            "--config-root",
                            str(config_root),
                            "--data-root",
                            str(data_root),
                        ]
                    )
                self.assertEqual(result, 0)
                outputs.append(json.loads(output.getvalue()))

            self.assertEqual(
                outputs,
                [
                    {"results": [], "status": "ok"},
                    {"results": [], "status": "ok"},
                ],
            )
            self.assertFalse((data_root / "releases").exists())



if __name__ == "__main__":
    unittest.main()
