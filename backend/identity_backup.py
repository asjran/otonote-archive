"""Consistent backup and restore of the identity SQLite database.

The backup uses the SQLite Backup API to stream a transactionally
consistent copy of the live database into a fresh file. The latest
snapshot is mirrored to ``identity-latest.sqlite3`` via a temp-file +
``os.replace`` so readers never observe a half-written file.

Every backup passes ``PRAGMA integrity_check`` before it is published;
``restore_identity_database`` re-verifies the file before promoting it
to the target location.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


class BackupError(RuntimeError):
    """Raised when a backup or restore cannot be completed safely."""


@dataclass(frozen=True)
class BackupResult:
    snapshot_path: Path
    latest_path: Path
    binding_count_at_snapshot: int


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_identity_database(
    *,
    source_path: Path,
    backup_root: Path,
    timestamp: Optional[str] = None,
) -> BackupResult:
    """Stream a consistent copy of ``source_path`` into ``backup_root``.

    Returns the snapshot path, the latest path, and the row count of the
    ``bindings`` table inside the snapshot (for tests / diagnostics).
    """

    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a Path")
    if not isinstance(backup_root, Path):
        raise TypeError("backup_root must be a Path")
    if not source_path.is_file():
        raise BackupError(f"source database does not exist: {source_path}")

    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or _utc_timestamp()
    latest_path = backup_root / "identity-latest.sqlite3"

    # Snapshot copy via the Backup API. ``stamp`` may collide if the
    # caller invokes ``backup_identity_database`` twice in the same
    # second; append a uniqueness suffix so callers never overwrite
    # historical snapshots by accident.
    stamp = _ensure_unique_snapshot_stamp(backup_root, stamp)
    snapshot_path = backup_root / f"identity-{stamp}.sqlite3"

    # Snapshot copy via the Backup API
    source_conn = _connect_query_only(source_path)
    snapshot_conn: Optional[sqlite3.Connection] = None
    snapshot_temp_path: Optional[Path] = None
    try:
        snapshot_temp_path = backup_root / f".identity-{stamp}.sqlite3.part"
        snapshot_conn = sqlite3.connect(str(snapshot_temp_path))
        source_conn.backup(snapshot_conn)
        snapshot_conn.commit()
        _verify_integrity(snapshot_conn, snapshot_temp_path)
    except Exception:
        if snapshot_conn is not None:
            snapshot_conn.close()
        if snapshot_temp_path is not None and snapshot_temp_path.exists():
            snapshot_temp_path.unlink()
        raise
    finally:
        if snapshot_conn is not None:
            snapshot_conn.close()
        source_conn.close()

    os.replace(snapshot_temp_path, snapshot_path)

    # Mirror to the deterministic latest path. Re-verify on read.
    _mirror_latest(snapshot_path, latest_path)

    return BackupResult(
        snapshot_path=snapshot_path,
        latest_path=latest_path,
        binding_count_at_snapshot=_count_bindings(latest_path),
    )


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_identity_database(
    *,
    backup_path: Path,
    target_path: Path,
) -> Path:
    """Copy ``backup_path`` to ``target_path`` after integrity verification."""

    if not isinstance(backup_path, Path):
        raise TypeError("backup_path must be a Path")
    if not isinstance(target_path, Path):
        raise TypeError("target_path must be a Path")
    if not backup_path.is_file():
        raise BackupError(f"backup does not exist: {backup_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.part")
    if temp_path.exists():
        temp_path.unlink()

    source_conn: Optional[sqlite3.Connection] = None
    target_conn: Optional[sqlite3.Connection] = None
    try:
        try:
            source_conn = _connect_query_only(backup_path)
        except sqlite3.DatabaseError as exc:
            raise BackupError(
                f"backup file is not a readable database: {backup_path}"
            ) from exc
        try:
            target_conn = sqlite3.connect(str(temp_path))
            source_conn.backup(target_conn)
            target_conn.commit()
            _verify_integrity(target_conn, temp_path)
        except sqlite3.DatabaseError as exc:
            raise BackupError(
                f"backup file failed to copy: {exc}"
            ) from exc
    except Exception:
        if target_conn is not None:
            target_conn.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()

    os.replace(temp_path, target_path)
    return target_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect_query_only(path: Path) -> sqlite3.Connection:
    # Keep the directory available for SQLite's WAL/SHM coordination while
    # refusing application-level writes through this source connection.
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _verify_integrity(connection: sqlite3.Connection, path: Path) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise BackupError(
            f"integrity_check failed for {path}: "
            + (repr(row[0]) if row else "no result")
        )


def _count_bindings(path: Path) -> int:
    conn = _connect_query_only(path)
    try:
        try:
            row = conn.execute("SELECT COUNT(*) FROM bindings").fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _mirror_latest(snapshot_path: Path, latest_path: Path) -> None:
    temp_path = latest_path.with_name(f".{latest_path.name}.part")
    if temp_path.exists():
        temp_path.unlink()
    source_conn = _connect_query_only(snapshot_path)
    target_conn: Optional[sqlite3.Connection] = None
    try:
        target_conn = sqlite3.connect(str(temp_path))
        source_conn.backup(target_conn)
        target_conn.commit()
        _verify_integrity(target_conn, temp_path)
    except Exception:
        if target_conn is not None:
            target_conn.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        if target_conn is not None:
            target_conn.close()
        source_conn.close()
    os.replace(temp_path, latest_path)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_unique_snapshot_stamp(backup_root: Path, stamp: str) -> str:
    """Return ``stamp`` (or a disambiguated variant) so the snapshot file
    does not overwrite an existing historical backup."""

    candidate = stamp
    suffix = 1
    while (backup_root / f"identity-{candidate}.sqlite3").exists():
        candidate = f"{stamp}-{suffix:02d}"
        suffix += 1
    return candidate


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Create one identity snapshot for systemd or an operator."""

    parser = argparse.ArgumentParser(prog="python -m backend.identity_backup")
    parser.add_argument("--source-path", required=True, type=Path)
    parser.add_argument("--backup-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = backup_identity_database(
            source_path=args.source_path,
            backup_root=args.backup_root,
        )
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"identity backup failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "snapshot": result.snapshot_path.name,
                "latest": result.latest_path.name,
                "bindings": result.binding_count_at_snapshot,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "BackupError",
    "BackupResult",
    "backup_identity_database",
    "main",
    "restore_identity_database",
]


if __name__ == "__main__":  # pragma: no cover - exercised by systemd smoke
    raise SystemExit(main())
