"""Lightweight identity binding store and module.

A single SQLite database holds one ``bindings`` table with the unique
constraint from design §9.2. The runtime enforces that there is at most
one binding per ``(identity_namespace, platform_user_id,
game_environment_id)`` tuple. New writes default to
``verification_status='claimed'``; writing ``verified`` is rejected until
a separately approved verification protocol is added.

The database file lives at ``<data_root>/identity/identity.sqlite3``.
WAL, ``foreign_keys=ON``, and ``busy_timeout`` are enabled for every
connection. All writes use an explicit transaction.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from backend.contracts import (
    Binding,
    BindingInput,
    Principal,
    VerificationStatus,
    require_utc_timestamp,
)


_MIGRATION_PATH = (
    Path(__file__).resolve().parent / "migrations" / "0001_bindings.sql"
)
_LATEST_MIGRATION_VERSION = 1
_ALLOWED_VERIFICATION_STATUSES: frozenset[str] = frozenset(
    status.value for status in VerificationStatus
)


class IdentityError(RuntimeError):
    """Base class for identity module errors."""


class IdentityConflict(IdentityError):
    """Raised when a write violates an invariant the schema cannot enforce."""


# ---------------------------------------------------------------------------
# Adapter credential
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterCredential:
    adapter_id: str
    bearer_token: str
    allowed_namespaces: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id.strip():
            raise ValueError("adapter_id cannot be empty")
        if not isinstance(self.bearer_token, str) or not self.bearer_token.strip():
            raise ValueError("bearer_token cannot be empty")
        normalized: list[str] = []
        for namespace in self.allowed_namespaces:
            if not isinstance(namespace, str) or not namespace.strip():
                raise ValueError("allowed_namespaces entries cannot be empty")
            normalized.append(namespace)
        object.__setattr__(self, "allowed_namespaces", tuple(normalized))


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class IdentityRepository:
    """Owns one SQLite database file and its migration lifecycle."""

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, Path):
            raise TypeError("database_path must be a Path")
        self._path = database_path

    @property
    def database_path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """Open / create the database and run pending migrations."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._apply_migrations(conn)
            conn.commit()

    def close(self) -> None:
        # Connection lifetime is per-context (see ``_connect``); the
        # repository does not hold an open connection between calls.
        return None

    # ----- internals -------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            str(self._path),
            isolation_level=None,  # we manage transactions explicitly
            timeout=5.0,
        )
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        current = self._current_version(conn)
        if current >= _LATEST_MIGRATION_VERSION:
            return
        migration_sql = _MIGRATION_PATH.read_text(encoding="utf-8")
        conn.executescript(migration_sql)
        # Insert every newly applied migration version. Use INSERT OR
        # IGNORE so reruns against a partially-upgraded DB are safe.
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (_LATEST_MIGRATION_VERSION,),
        )

    @staticmethod
    def _current_version(conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # ----- row helpers -----------------------------------------------------

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> Binding:
        return Binding(
            id=str(row["id"]),
            identity_namespace=row["identity_namespace"],
            platform_user_id=row["platform_user_id"],
            game_environment_id=row["game_environment_id"],
            game_account_id=row["game_account_id"],
            verification_status=VerificationStatus(row["verification_status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# Binding module
# ---------------------------------------------------------------------------


class BindingModule:
    """Stateless façade that calls :class:`IdentityRepository` for every op."""

    class NotVisible(IdentityError):
        """Raised when a binding ID does not belong to the calling principal."""

    class ForbiddenVerificationStatus(IdentityError):
        """Raised when a write attempts to set ``verification_status='verified'``.

        A separately approved verification protocol must whitelist this
        status before it can be written; the lightweight module never does.
        """

    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository
        if not isinstance(repository, IdentityRepository):
            raise TypeError("repository must be an IdentityRepository")

    def close(self) -> None:
        """Release any resources held by the underlying repository."""

        self._repository.close()

    # ----- public API ------------------------------------------------------

    def list_bindings(
        self, principal: Principal, environment_id: str
    ) -> tuple[Binding, ...]:
        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        if not isinstance(environment_id, str) or not environment_id.strip():
            raise ValueError("environment_id cannot be empty")
        with self._repository._connect() as conn:  # noqa: SLF001 - internal access
            rows = conn.execute(
                """
                SELECT id, identity_namespace, platform_user_id,
                       game_environment_id, game_account_id,
                       verification_status, created_at, updated_at
                FROM bindings
                WHERE identity_namespace = ? AND platform_user_id = ?
                  AND game_environment_id = ?
                ORDER BY id ASC
                """,
                (
                    principal.identity_namespace,
                    principal.platform_user_id,
                    environment_id,
                ),
            ).fetchall()
        return tuple(IdentityRepository._row_to_binding(row) for row in rows)

    def upsert_binding(
        self, principal: Principal, input_: BindingInput
    ) -> Binding:
        """Idempotent upsert that always writes ``verification_status=claimed``."""

        return self.upsert_binding_with_status(
            principal, input_, requested_status=VerificationStatus.CLAIMED
        )

    def upsert_binding_with_status(
        self,
        principal: Principal,
        input_: BindingInput,
        *,
        requested_status: Optional[VerificationStatus] = None,
    ) -> Binding:
        status = requested_status or VerificationStatus.CLAIMED
        if status not in (VerificationStatus.CLAIMED, VerificationStatus.REVOKED):
            raise BindingModule.ForbiddenVerificationStatus(
                "verification_status='verified' requires a separate approved protocol"
            )
        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        if not isinstance(input_, BindingInput):
            raise TypeError("input_ must be a BindingInput")
        # The row's identity is always the authenticated Principal —
        # the adapter's claimed headers, not the body. The body's
        # identity fields must agree with the Principal so callers
        # cannot accidentally write a row under the wrong identity.
        if (
            input_.identity_namespace != principal.identity_namespace
            or input_.platform_user_id != principal.platform_user_id
        ):
            raise ValueError(
                "BindingInput identity fields must match the authenticated Principal"
            )

        identity_namespace = principal.identity_namespace
        platform_user_id = principal.platform_user_id
        game_environment_id = input_.game_environment_id
        game_account_id = input_.game_account_id

        now = _utc_now()
        with self._repository.transaction() as conn:
            existing = conn.execute(
                """
                SELECT id, created_at FROM bindings
                WHERE identity_namespace = ? AND platform_user_id = ?
                  AND game_environment_id = ?
                """,
                (
                    identity_namespace,
                    platform_user_id,
                    game_environment_id,
                ),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO bindings (
                        identity_namespace, platform_user_id,
                        game_environment_id, game_account_id,
                        verification_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity_namespace,
                        platform_user_id,
                        game_environment_id,
                        game_account_id,
                        status.value,
                        now,
                        now,
                    ),
                )
                binding_id = str(cursor.lastrowid)
            else:
                binding_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE bindings
                    SET game_account_id = ?, verification_status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (game_account_id, status.value, now, binding_id),
                )
            row = conn.execute(
                """
                SELECT id, identity_namespace, platform_user_id,
                       game_environment_id, game_account_id,
                       verification_status, created_at, updated_at
                FROM bindings WHERE id = ?
                """,
                (binding_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise IdentityError("binding disappeared after upsert")
        return IdentityRepository._row_to_binding(row)

    def remove_binding(self, principal: Principal, binding_id: str) -> None:
        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise ValueError("binding_id cannot be empty")
        try:
            binding_int_id = int(binding_id)
        except ValueError as exc:
            raise BindingModule.NotVisible(
                "binding does not exist for the current principal"
            ) from exc

        with self._repository.transaction() as conn:
            owner = conn.execute(
                """
                SELECT identity_namespace, platform_user_id FROM bindings
                WHERE id = ?
                """,
                (binding_int_id,),
            ).fetchone()
            if owner is None:
                # Repeated remove is idempotent for the owner; for any
                # other principal we still report NotVisible to avoid
                # leaking existence.
                return
            if (
                owner["identity_namespace"] != principal.identity_namespace
                or owner["platform_user_id"] != principal.platform_user_id
            ):
                raise BindingModule.NotVisible(
                    "binding does not exist for the current principal"
                )
            conn.execute(
                "DELETE FROM bindings WHERE id = ?",
                (binding_int_id,),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "AdapterCredential",
    "BindingModule",
    "IdentityConflict",
    "IdentityError",
    "IdentityRepository",
]