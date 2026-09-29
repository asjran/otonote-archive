from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.monitor.collect import backup_database, database_is_healthy


class LegacyConnection:
    """Expose the SQLite APIs available on the production Python runtime."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def commit(self) -> None:
        self.connection.commit()

    def execute(self, statement: str):
        return self.connection.execute(statement)


class MonitorBackupTest(unittest.TestCase):
    def test_backs_up_database_without_connection_backup_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "monitor.sqlite3"
            backup = root / "monitor.sqlite3.backup"
            connection = sqlite3.connect(str(source))
            connection.execute("CREATE TABLE metrics(value TEXT NOT NULL)")
            connection.execute("INSERT INTO metrics(value) VALUES('production')")

            backup_database(LegacyConnection(connection), backup)
            connection.close()

            self.assertTrue(database_is_healthy(backup))
            copied = sqlite3.connect(str(backup))
            try:
                self.assertEqual(
                    copied.execute("SELECT value FROM metrics").fetchone(),
                    ("production",),
                )
            finally:
                copied.close()


if __name__ == "__main__":
    unittest.main()
