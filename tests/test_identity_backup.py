"""T4 tests for ``backend.identity_backup``.

The backup path uses the SQLite Backup API to stream a consistent copy to
``<backup_root>/identity-<timestamp>.sqlite3`` plus an atomically replaced
``identity-latest.sqlite3``. The tests build a fresh identity database,
write known bindings, snapshot it, and confirm the snapshot is restorable
into a separate location.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.identity import (  # noqa: E402
    AdapterCredential,
    BindingModule,
    IdentityRepository,
)
from backend.identity_backup import (  # noqa: E402
    BackupError,
    _connect_query_only,
    backup_identity_database,
    main,
    restore_identity_database,
)


def _open(root: Path) -> BindingModule:
    repository = IdentityRepository(root / "identity.sqlite3")
    repository.initialize()
    return BindingModule(repository)


def _upsert(module: BindingModule, account: str, *, user: str = "alice") -> int:
    binding = module.upsert_binding_with_status(
        Principal_for_test(user=user),
        Input_for_test(account=account, user=user),
        requested_status=None,
    )
    return int(binding.id)


def Principal_for_test(user: str = "alice"):
    from backend.contracts import Principal
    return Principal(
        adapter_id="adapter-fixture",
        identity_namespace="qq-official:fixture-app",
        platform_user_id=user,
    )


def Input_for_test(account: str, *, user: str = "alice"):
    from backend.contracts import BindingInput
    return BindingInput(
        identity_namespace="qq-official:fixture-app",
        platform_user_id=user,
        game_environment_id="global-production",
        game_account_id=account,
    )


class BackupWriteTest(unittest.TestCase):
    def test_source_connection_is_query_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _open(root)

            connection = _connect_query_only(root / "identity.sqlite3")
            try:
                self.assertEqual(
                    connection.execute("PRAGMA query_only").fetchone()[0], 1
                )
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden (id INTEGER)")
            finally:
                connection.close()

    def test_backup_accepts_a_read_only_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "src"
            _open(source_root)
            source_path = source_root / "identity.sqlite3"
            os.chmod(source_path, 0o444)
            os.chmod(source_root, 0o555)
            try:
                result = backup_identity_database(
                    source_path=source_path,
                    backup_root=root / "backups",
                )
                self.assertTrue(result.latest_path.is_file())
            finally:
                os.chmod(source_root, 0o755)
                os.chmod(source_path, 0o644)

    def test_backup_writes_a_timestamped_file_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open(root / "src")
            binding_id = _upsert(module, "acc-001")

            backup_root = root / "backups"
            result = backup_identity_database(
                source_path=root / "src" / "identity.sqlite3",
                backup_root=backup_root,
            )

            self.assertTrue(result.snapshot_path.is_file())
            self.assertTrue(result.latest_path.is_file())
            self.assertEqual(result.binding_count_at_snapshot, 1)

            latest = sqlite3.connect(str(result.latest_path))
            try:
                rows = latest.execute("SELECT id FROM bindings").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], binding_id)
            finally:
                latest.close()

    def test_backup_passes_integrity_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open(root / "src")
            _upsert(module, "acc-001")
            _upsert(module, "acc-002")

            result = backup_identity_database(
                source_path=root / "src" / "identity.sqlite3",
                backup_root=root / "backups",
            )

            conn = sqlite3.connect(str(result.latest_path))
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()
                self.assertEqual(check, ("ok",))
            finally:
                conn.close()

    def test_backup_atomic_overwrite_of_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open(root / "src")
            _upsert(module, "acc-001", user="alice")

            first = backup_identity_database(
                source_path=root / "src" / "identity.sqlite3",
                backup_root=root / "backups",
            )

            _upsert(module, "acc-002", user="bob")
            second = backup_identity_database(
                source_path=root / "src" / "identity.sqlite3",
                backup_root=root / "backups",
            )

            # ``latest_path`` is the deterministic mirror so it stays the
            # same; the snapshot paths MUST differ.
            self.assertEqual(first.latest_path, second.latest_path)
            self.assertNotEqual(first.snapshot_path, second.snapshot_path)

            conn = sqlite3.connect(str(second.latest_path))
            try:
                rows = conn.execute("SELECT COUNT(*) FROM bindings").fetchone()
                self.assertEqual(rows[0], 2)
            finally:
                conn.close()


class BackupRestoreTest(unittest.TestCase):
    def test_restore_into_separate_directory_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open(root / "src")
            _upsert(module, "acc-001", user="alice")
            _upsert(module, "acc-002", user="bob")
            result = backup_identity_database(
                source_path=root / "src" / "identity.sqlite3",
                backup_root=root / "backups",
            )

            restored = restore_identity_database(
                backup_path=result.latest_path,
                target_path=root / "restored" / "identity.sqlite3",
            )

            self.assertTrue(restored.is_file())
            conn = sqlite3.connect(str(restored))
            try:
                rows = conn.execute("SELECT COUNT(*) FROM bindings").fetchone()
                self.assertEqual(rows[0], 2)
            finally:
                conn.close()

    def test_restore_fails_on_corrupt_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup_path = root / "broken.sqlite3"
            backup_path.write_bytes(b"not a sqlite database")

            with self.assertRaises(BackupError):
                restore_identity_database(
                    backup_path=backup_path,
                    target_path=root / "restored" / "identity.sqlite3",
                )


class BackupFailureTest(unittest.TestCase):
    def test_missing_source_raises_backup_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(BackupError):
                backup_identity_database(
                    source_path=Path(temporary) / "missing.sqlite3",
                    backup_root=Path(temporary) / "backups",
                )


class BackupCliTest(unittest.TestCase):
    def test_cli_writes_real_snapshot_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _open(root / "src")

            exit_code = main(
                [
                    "--source-path",
                    str(root / "src" / "identity.sqlite3"),
                    "--backup-root",
                    str(root / "backups"),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "backups" / "identity-latest.sqlite3").is_file())
            self.assertEqual(
                len(list((root / "backups").glob("identity-20*.sqlite3"))),
                1,
            )

    def test_python_module_entrypoint_writes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _open(root / "src")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "backend.identity_backup",
                    "--source-path",
                    str(root / "src" / "identity.sqlite3"),
                    "--backup-root",
                    str(root / "backups"),
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((root / "backups" / "identity-latest.sqlite3").is_file())

    def test_cli_returns_nonzero_when_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            exit_code = main(
                [
                    "--source-path",
                    str(root / "missing.sqlite3"),
                    "--backup-root",
                    str(root / "backups"),
                ]
            )

            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
