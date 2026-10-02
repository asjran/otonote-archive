import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.sync_server_data import (
    SourceConfig,
    SyncConfig,
    SyncError,
    build_rsync_command,
    load_config,
    sync_server_data,
)


VALID_CONFIG = """\
version = 1

[server]
sshTarget = "aliyun"

[backup]
destination = "../backups"

[[sources]]
name = "resource-data"
remotePath = "/srv/ournotes-data"
enabled = true
required = true
excludes = ["locks/**", "*.part"]

[[sources]]
name = "site-shadow"
remotePath = "/srv/ournotes-site"
enabled = true
required = false
excludes = ["*.part"]
"""


class FakeRunner:
    def __init__(
        self,
        *,
        missing_paths=(),
        fail_rsync=False,
        payload=b"resource-payload",
    ):
        self.missing_paths = set(missing_paths)
        self.fail_rsync = fail_rsync
        self.payload = payload
        self.commands = []

    def __call__(self, command, *, capture_output=False, cwd=None):
        command = list(command)
        self.commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="a" * 40 + "\n", stderr=""
            )
        if command[0] == "ssh":
            remote_command = command[-1]
            missing = any(path in remote_command for path in self.missing_paths)
            return subprocess.CompletedProcess(
                command,
                1 if missing else 0,
                stdout="",
                stderr="",
            )
        if command[0] == "rsync":
            if self.fail_rsync:
                return subprocess.CompletedProcess(command, 23)

            destination = Path(command[-1].rstrip("/"))
            destination.mkdir(parents=True, exist_ok=True)
            link_argument = next(
                (
                    argument
                    for argument in command
                    if argument.startswith("--link-dest=")
                ),
                None,
            )
            previous_file = None
            if link_argument is not None:
                previous_file = (
                    Path(link_argument.split("=", 1)[1]) / "payload.bin"
                )
            destination_file = destination / "payload.bin"
            if (
                previous_file is not None
                and previous_file.is_file()
                and previous_file.read_bytes() == self.payload
            ):
                os.link(previous_file, destination_file)
            else:
                destination_file.write_bytes(self.payload)
            return subprocess.CompletedProcess(command, 0)
        raise AssertionError(f"unexpected command: {command}")


class ServerDataSyncConfigTests(unittest.TestCase):
    def _write_config(self, root: Path, content: str = VALID_CONFIG) -> Path:
        repository = root / "repo"
        repository.mkdir()
        config_path = repository / "server-sync.toml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_loads_valid_config_and_resolves_destination_from_repo_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = self._write_config(root)

            config = load_config(config_path, config_path.parent)

            self.assertEqual(config.ssh_target, "aliyun")
            self.assertEqual(config.destination, (root / "backups").resolve())
            self.assertEqual(
                [source.name for source in config.sources],
                ["resource-data", "site-shadow"],
            )
            self.assertTrue(config.sources[0].required)
            self.assertFalse(config.sources[1].required)

    def test_rejects_duplicate_source_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = VALID_CONFIG.replace(
                'name = "site-shadow"', 'name = "resource-data"'
            )
            config_path = self._write_config(root, content)

            with self.assertRaisesRegex(
                SyncError, "duplicate source name: resource-data"
            ):
                load_config(config_path, config_path.parent)

    def test_rejects_unsafe_remote_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = VALID_CONFIG.replace(
                'remotePath = "/srv/ournotes-data"',
                'remotePath = "/srv/ournotes-data;touch-bad"',
            )
            config_path = self._write_config(root, content)

            with self.assertRaisesRegex(SyncError, "safe path characters"):
                load_config(config_path, config_path.parent)

    def test_rejects_destination_inside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = VALID_CONFIG.replace(
                'destination = "../backups"',
                'destination = "backups"',
            )
            config_path = self._write_config(root, content)

            with self.assertRaisesRegex(SyncError, "outside the Git checkout"):
                load_config(config_path, config_path.parent)


class ServerDataSnapshotTests(unittest.TestCase):
    def _config(self, root: Path) -> SyncConfig:
        return SyncConfig(
            ssh_target="aliyun",
            destination=root / "backups",
            sources=(
                SourceConfig(
                    name="resource-data",
                    remote_path="/srv/ournotes-data",
                    enabled=True,
                    required=True,
                    excludes=("locks/**", "*.part"),
                ),
                SourceConfig(
                    name="site-shadow",
                    remote_path="/srv/ournotes-site",
                    enabled=True,
                    required=False,
                    excludes=("*.part",),
                ),
            ),
        )

    def test_builds_rsync_command_with_excludes_and_link_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            source = config.sources[0]
            command = build_rsync_command(
                config,
                source,
                root / "partial" / source.name,
                root / "previous" / source.name,
            )

            self.assertIn(
                f"--link-dest={(root / 'previous' / source.name).resolve()}",
                command,
            )
            self.assertIn("--exclude=locks/**", command)
            self.assertIn("--exclude=*.part", command)
            self.assertNotIn("--delete", command)
            self.assertEqual(
                command[-2], "aliyun:/srv/ournotes-data/"
            )

    def test_dry_run_checks_remote_without_creating_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            runner = FakeRunner(missing_paths={"/srv/ournotes-site"})

            result = sync_server_data(
                config,
                dry_run=True,
                runner=runner,
                check_dependencies=False,
            )

            self.assertIsNone(result)
            self.assertFalse(config.destination.exists())
            self.assertEqual(
                [command[0] for command in runner.commands], ["ssh", "ssh"]
            )

    def test_required_remote_directory_missing_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            runner = FakeRunner(
                missing_paths={"/srv/ournotes-data", "/srv/ournotes-site"}
            )

            with self.assertRaisesRegex(
                SyncError, "required remote directory does not exist"
            ):
                sync_server_data(
                    config,
                    runner=runner,
                    check_dependencies=False,
                )

            self.assertFalse(config.destination.exists())

    def test_failure_keeps_partial_and_does_not_update_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            runner = FakeRunner(fail_rsync=True)

            with self.assertRaisesRegex(SyncError, "partial snapshot kept"):
                sync_server_data(
                    config,
                    runner=runner,
                    timestamp="20260718T120000Z",
                    check_dependencies=False,
                )

            self.assertTrue(
                (
                    config.destination / ".20260718T120000Z.partial"
                ).is_dir()
            )
            self.assertFalse(
                (config.destination / "20260718T120000Z").exists()
            )
            self.assertFalse((config.destination / "latest").exists())

    def test_success_writes_manifest_and_skips_optional_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            runner = FakeRunner(missing_paths={"/srv/ournotes-site"})

            snapshot = sync_server_data(
                config,
                runner=runner,
                timestamp="20260718T120000Z",
                check_dependencies=False,
            )

            self.assertEqual(
                snapshot, config.destination / "20260718T120000Z"
            )
            self.assertEqual(
                os.readlink(config.destination / "latest"),
                "20260718T120000Z",
            )
            manifest = json.loads(
                (snapshot / "backup-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["gitCommit"], "a" * 40)
            self.assertEqual(manifest["sources"][0]["status"], "synced")
            self.assertEqual(manifest["sources"][0]["files"], 1)
            self.assertEqual(manifest["sources"][1]["status"], "skipped")

    def test_unchanged_file_is_hard_linked_from_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            runner = FakeRunner(missing_paths={"/srv/ournotes-site"})

            first = sync_server_data(
                config,
                runner=runner,
                timestamp="20260718T120000Z",
                check_dependencies=False,
            )
            second = sync_server_data(
                config,
                runner=runner,
                timestamp="20260718T130000Z",
                check_dependencies=False,
            )

            first_file = first / "resource-data" / "payload.bin"
            second_file = second / "resource-data" / "payload.bin"
            self.assertEqual(first_file.stat().st_ino, second_file.stat().st_ino)
            manifest = json.loads(
                (second / "backup-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["previousSnapshot"], "20260718T120000Z"
            )
            rsync_commands = [
                command for command in runner.commands if command[0] == "rsync"
            ]
            self.assertTrue(
                any(
                    argument.startswith("--link-dest=")
                    for argument in rsync_commands[-1]
                )
            )

    @unittest.skipUnless(shutil.which("rsync"), "rsync is required")
    def test_real_rsync_reuses_files_and_excludes_runtime_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            first = root / "first"
            second = root / "second"
            (source / "locks").mkdir(parents=True)
            first.mkdir()
            second.mkdir()
            (source / "stable.bin").write_bytes(b"stable")
            (source / "transfer.part").write_bytes(b"partial")
            (source / "locks" / "worker.lock").write_bytes(b"locked")

            common_arguments = [
                "rsync",
                "-a",
                "--safe-links",
                "--exclude=locks/**",
                "--exclude=*.part",
            ]
            subprocess.run(
                [*common_arguments, f"{source}/", f"{first}/"],
                check=True,
            )
            subprocess.run(
                [
                    *common_arguments,
                    f"--link-dest={first}",
                    f"{source}/",
                    f"{second}/",
                ],
                check=True,
            )

            self.assertEqual(
                (first / "stable.bin").stat().st_ino,
                (second / "stable.bin").stat().st_ino,
            )
            self.assertFalse((second / "transfer.part").exists())
            self.assertFalse((second / "locks" / "worker.lock").exists())


if __name__ == "__main__":
    unittest.main()
