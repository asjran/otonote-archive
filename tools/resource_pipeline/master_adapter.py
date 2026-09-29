"""Atomic acquisition and lineage recording for encrypted Master tables."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from analysis.crypto.decrypt_master import decrypt_master_file


class MasterAdapterError(RuntimeError):
    """Raised when a complete Master snapshot cannot be acquired."""


@dataclass(frozen=True)
class MasterTableArtifact:
    name: str
    source: str
    encrypted_sha256: str
    decrypted_sha256: str
    projected_sha256: str
    byte_size: int
    output: Path


@dataclass(frozen=True)
class MasterSnapshot:
    version: str
    tables: tuple[MasterTableArtifact, ...]
    catalog_evidence: Mapping[str, tuple[str, ...]]
    output_dir: Path
    manifest_sha256: str

    def table(self, name: str) -> MasterTableArtifact:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)


class MasterAdapter:
    def __init__(self, *, decryptor: Callable[..., dict[str, object]] = decrypt_master_file):
        self._decryptor = decryptor

    def acquire(
        self,
        manifest_path: Path,
        *,
        source_root: Path,
        output_root: Path,
        crypto_material: Mapping[str, bytes],
    ) -> MasterSnapshot:
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MasterAdapterError("invalid Master manifest JSON") from error
        if not isinstance(manifest, dict):
            raise MasterAdapterError("Master manifest root must be an object")
        version = manifest.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version):
            raise MasterAdapterError("Master version must be a path-safe identifier")
        tables = manifest.get("tables")
        if not isinstance(tables, list) or not tables:
            raise MasterAdapterError("Master manifest must contain tables")
        for required in ("salt", "key", "iv"):
            if required not in crypto_material or not isinstance(crypto_material[required], bytes):
                raise MasterAdapterError(f"missing binary crypto material: {required}")

        output_root.mkdir(parents=True, exist_ok=True)
        final_dir = output_root / version
        if final_dir.exists():
            raise MasterAdapterError(f"Master snapshot already exists: {version}")
        stage = Path(tempfile.mkdtemp(prefix=f".{version}.partial-", dir=output_root))
        records: list[dict[str, Any]] = []
        names: set[str] = set()
        try:
            for index, entry in enumerate(tables):
                if not isinstance(entry, dict):
                    raise MasterAdapterError(f"table {index} must be an object")
                name = entry.get("name")
                relative_source = entry.get("source")
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                    raise MasterAdapterError(f"invalid table name at index {index}")
                if name in names:
                    raise MasterAdapterError(f"duplicate Master table: {name}")
                names.add(name)
                if not isinstance(relative_source, str) or not relative_source:
                    raise MasterAdapterError(f"invalid source for {name}")
                source = _confined_path(source_root, relative_source)
                destination = stage / "tables" / f"{name}.json"
                try:
                    encrypted = source.read_bytes()
                    expected_hash = entry.get("sha256")
                    encrypted_hash = hashlib.sha256(encrypted).hexdigest()
                    if expected_hash is not None and expected_hash != encrypted_hash:
                        raise ValueError("encrypted SHA-256 mismatch")
                    self._decryptor(
                        source,
                        destination,
                        salt=crypto_material["salt"],
                        key=crypto_material["key"],
                        iv=crypto_material["iv"],
                    )
                    decrypted = destination.read_bytes()
                    parsed = json.loads(decrypted)
                    projected = json.dumps(
                        parsed,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                except Exception as error:
                    raise MasterAdapterError(
                        f"Master table {name} failed: {type(error).__name__}: {error}"
                    ) from None
                records.append(
                    {
                        "name": name,
                        "source": relative_source,
                        "encryptedSha256": encrypted_hash,
                        "decryptedSha256": hashlib.sha256(decrypted).hexdigest(),
                        "projectedSha256": hashlib.sha256(projected).hexdigest(),
                        "byteSize": len(decrypted),
                    }
                )

            evidence = _catalog_evidence(manifest.get("catalogEvidence", {}))
            lineage = {
                "version": version,
                "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "tables": records,
                "catalogEvidence": {key: list(values) for key, values in evidence.items()},
            }
            (stage / "lineage.json").write_text(
                json.dumps(lineage, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(stage, final_dir)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

        artifacts = tuple(
            MasterTableArtifact(
                name=record["name"],
                source=record["source"],
                encrypted_sha256=record["encryptedSha256"],
                decrypted_sha256=record["decryptedSha256"],
                projected_sha256=record["projectedSha256"],
                byte_size=record["byteSize"],
                output=final_dir / "tables" / f"{record['name']}.json",
            )
            for record in records
        )
        return MasterSnapshot(
            version=version,
            tables=artifacts,
            catalog_evidence=evidence,
            output_dir=final_dir,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )


def _confined_path(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise MasterAdapterError("Master source escapes source_root")
    if not candidate.is_file():
        raise MasterAdapterError(f"Master source is missing: {relative}")
    return candidate


def _catalog_evidence(raw: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise MasterAdapterError("catalogEvidence must be an object")
    result: dict[str, tuple[str, ...]] = {}
    for name, selectors in raw.items():
        if not isinstance(name, str) or not isinstance(selectors, list):
            raise MasterAdapterError("invalid catalogEvidence entry")
        result[name] = tuple(dict.fromkeys(str(selector) for selector in selectors))
    return result
