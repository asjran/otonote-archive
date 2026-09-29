"""Local content-addressed storage with atomic object commits."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class ObjectStoreError(RuntimeError):
    """Raised when an object cannot be verified or committed."""


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    byte_size: int
    path: Path
    reused: bool


@dataclass(frozen=True)
class ObjectMetadata:
    sha256: str
    byte_size: int
    path: Path


class FileObjectStore:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.object_root = data_root / "store/sha256"
        self.work_root = data_root / "work"

    @staticmethod
    def _validate_hash(value: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("expected_sha256 must be 64 lowercase hex characters")

    @staticmethod
    def _validate_job_id(value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("job_id must be a path-safe identifier")

    def object_path(self, sha256: str) -> Path:
        self._validate_hash(sha256)
        return self.object_root / sha256[:2] / sha256[2:4] / sha256

    def has_object(self, sha256: str) -> bool:
        return self.object_path(sha256).is_file()

    def open_object(self, sha256: str) -> BinaryIO:
        return self.object_path(sha256).open("rb")

    def object_metadata(self, sha256: str) -> ObjectMetadata:
        path = self.object_path(sha256)
        return ObjectMetadata(sha256=sha256, byte_size=path.stat().st_size, path=path)

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        job_id: str,
        expected_sha256: str | None = None,
    ) -> StoredObject:
        self._validate_job_id(job_id)
        if expected_sha256 is not None:
            self._validate_hash(expected_sha256)

        work_dir = self.work_root / job_id / "objects"
        work_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_size = 0
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=work_dir,
                prefix="object-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
                output.flush()
                os.fsync(output.fileno())

            actual_sha256 = digest.hexdigest()
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                raise ObjectStoreError(
                    "object SHA-256 mismatch: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )

            target = self.object_path(actual_sha256)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.stat().st_size != byte_size:
                    raise ObjectStoreError(
                        f"stored object size mismatch for {actual_sha256}"
                    )
                temporary_path.unlink()
                temporary_path = None
                return StoredObject(actual_sha256, byte_size, target, True)

            os.replace(temporary_path, target)
            temporary_path = None
            return StoredObject(actual_sha256, byte_size, target, False)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
