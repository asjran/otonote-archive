"""Release validation concentrated behind one manifest-level interface."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import Channel, Region
from .object_store import FileObjectStore


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


class ContentValidator:
    def __init__(
        self,
        *,
        object_store: FileObjectStore,
        max_critical_table_drop_ratio: float = 0.5,
    ):
        if not 0 <= max_critical_table_drop_ratio <= 1:
            raise ValueError("max_critical_table_drop_ratio must be between 0 and 1")
        self._store = object_store
        self._max_drop_ratio = max_critical_table_drop_ratio

    def validate(
        self,
        candidate: Mapping[str, Any],
        *,
        baseline: Mapping[str, Any] | None = None,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        self._validate_objects(candidate, issues)
        self._validate_identity(candidate, issues)
        self._validate_version_evidence(candidate, issues)
        self._validate_critical_tables(candidate, baseline, issues)
        self._validate_references(candidate, issues)
        self._validate_localized_text(candidate, issues)
        self._validate_publishable_output(candidate, issues)
        self._validate_remote_code(candidate, baseline, issues)
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _validate_publishable_output(
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        secret_patterns = (
            re.compile(r"authorization\s*[:=]", re.IGNORECASE),
            re.compile(r"bearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE),
            re.compile(
                r"(?:cookie|password|passwd|token|secret|device[-_]?id)\s*[:=]",
                re.IGNORECASE,
            ),
        )

        def walk(value: Any, path: str) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    if normalized in {"rawresponse", "privateresponse"}:
                        issues.append(
                            ValidationIssue(
                                "private_response_detected",
                                "raw or private server responses cannot be published",
                                child_path,
                            )
                        )
                        continue
                    if normalized in {
                        "authorization",
                        "cookie",
                        "password",
                        "passwd",
                        "token",
                        "secret",
                        "deviceid",
                    }:
                        issues.append(
                            ValidationIssue(
                                "output_secret_detected",
                                "publishable output contains secret or device material",
                                child_path,
                            )
                        )
                        continue
                    walk(child, child_path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")
            elif isinstance(value, str) and any(
                pattern.search(value) for pattern in secret_patterns
            ):
                issues.append(
                    ValidationIssue(
                        "output_secret_detected",
                        "publishable output contains secret or device material",
                        path,
                    )
                )

        walk(candidate, "")

    @staticmethod
    def _validate_remote_code(
        candidate: Mapping[str, Any],
        baseline: Mapping[str, Any] | None,
        issues: list[ValidationIssue],
    ) -> None:
        candidate_hash = _version_value(candidate, "remoteCodeHash")
        baseline_hash = _version_value(baseline, "remoteCodeHash") if baseline else None
        if candidate_hash is None or candidate_hash == baseline_hash:
            return
        approvals = candidate.get("approvals")
        remote_approval = (
            approvals.get("remoteCode") if isinstance(approvals, Mapping) else None
        )
        approval_valid = (
            isinstance(remote_approval, Mapping)
            and remote_approval.get("hash") == candidate_hash
            and isinstance(remote_approval.get("confirmedBy"), str)
            and bool(remote_approval["confirmedBy"].strip())
            and isinstance(remote_approval.get("confirmedAt"), str)
            and re.match(r"^\d{4}-\d{2}-\d{2}T", remote_approval["confirmedAt"])
            is not None
            and isinstance(remote_approval.get("evidence"), str)
            and bool(remote_approval["evidence"].strip())
        )
        if not approval_valid:
            issues.append(
                ValidationIssue(
                    "remote_code_review_required",
                    "changed remote executable content requires matching manual approval",
                    "approvals.remoteCodeHash",
                )
            )

    @staticmethod
    def _validate_references(
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        references = candidate.get("references", [])
        available = candidate.get("availableTargets", [])
        if not isinstance(references, list) or not isinstance(available, list):
            issues.append(
                ValidationIssue(
                    "references_invalid",
                    "references and availableTargets must be arrays",
                    "references",
                )
            )
            return
        available_set = {value for value in available if isinstance(value, str)}
        for index, reference in enumerate(references):
            if not isinstance(reference, dict):
                issues.append(
                    ValidationIssue(
                        "references_invalid",
                        "reference must be a mapping",
                        f"references[{index}]",
                    )
                )
                continue
            target = reference.get("target")
            if not isinstance(target, str) or target not in available_set:
                issues.append(
                    ValidationIssue(
                        "reference_unresolved",
                        "card, music, event or asset reference cannot be resolved",
                        f"references[{index}].target",
                    )
                )

    @staticmethod
    def _validate_localized_text(
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        entities = candidate.get("entities", [])
        if not isinstance(entities, list):
            issues.append(
                ValidationIssue(
                    "entities_invalid",
                    "entities must be an array",
                    "entities",
                )
            )
            return
        for index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                issues.append(
                    ValidationIssue(
                        "entities_invalid",
                        "entity must be a mapping",
                        f"entities[{index}]",
                    )
                )
                continue
            localized = entity.get("localizedText")
            if not isinstance(localized, dict):
                issues.append(
                    ValidationIssue(
                        "localized_text_flattened",
                        "LocalizedText must remain a locale mapping",
                        f"entities[{index}].localizedText",
                    )
                )
                continue
            if not localized or any(
                not isinstance(value, str) or not value.strip()
                for value in localized.values()
            ):
                issues.append(
                    ValidationIssue(
                        "localized_text_empty",
                        "LocalizedText cannot be empty or cleared",
                        f"entities[{index}].localizedText",
                    )
                )

    def _validate_critical_tables(
        self,
        candidate: Mapping[str, Any],
        baseline: Mapping[str, Any] | None,
        issues: list[ValidationIssue],
    ) -> None:
        candidate_rows = _critical_rows(candidate)
        baseline_rows = _critical_rows(baseline) if baseline is not None else {}
        if not candidate_rows:
            issues.append(
                ValidationIssue(
                    "critical_table_statistics_missing",
                    "critical Master table statistics are required",
                    "statistics.criticalTableRows",
                )
            )
        table_names = set(candidate_rows) | set(baseline_rows)
        for table_name in sorted(table_names):
            after = candidate_rows.get(table_name)
            before = baseline_rows.get(table_name)
            path = f"statistics.criticalTableRows.{table_name}"
            if type(after) is not int or after <= 0:
                issues.append(
                    ValidationIssue(
                        "critical_table_empty",
                        f"critical Master table {table_name} must be non-empty",
                        path,
                    )
                )
                continue
            if type(before) is int and before > 0:
                drop_ratio = (before - after) / before
                if drop_ratio > self._max_drop_ratio:
                    issues.append(
                        ValidationIssue(
                            "critical_table_drop",
                            f"critical Master table {table_name} dropped beyond "
                            "the configured threshold",
                            path,
                        )
                    )

    @staticmethod
    def _validate_identity(
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        content = candidate.get("contentRelease")
        client = candidate.get("clientBuild")
        if not isinstance(content, dict) or not isinstance(client, dict):
            issues.append(
                ValidationIssue(
                    "identity_invalid",
                    "release and ClientBuild identities are required",
                    "contentRelease",
                )
            )
            return
        region = content.get("region")
        channel = content.get("channel")
        release_id = content.get("id")
        observed_build = content.get("observedByClientBuildRef")
        client_id = client.get("id")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (region, channel, release_id, observed_build, client_id)
        ):
            issues.append(
                ValidationIssue(
                    "identity_invalid",
                    "release identity fields must be non-empty strings",
                    "contentRelease",
                )
            )
            return
        prefix = f"{region}-{channel}-"
        if (
            region not in {value.value for value in Region}
            or channel not in {value.value for value in Channel}
            or observed_build != client_id
            or not release_id.startswith(prefix)
            or not client_id.startswith(prefix)
        ):
            issues.append(
                ValidationIssue(
                    "identity_mismatch",
                    "Region, Channel, ClientBuild and ContentRelease "
                    "identities do not match",
                    "contentRelease",
                )
            )

    def _validate_version_evidence(
        self,
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        content = candidate.get("contentRelease")
        explicit_evidence = candidate.get("evidence")
        evidence = self._derive_object_evidence(candidate)
        if isinstance(explicit_evidence, Mapping):
            evidence.update(explicit_evidence)
        vector = content.get("versionVector") if isinstance(content, dict) else None
        if not isinstance(vector, dict) or not evidence:
            issues.append(
                ValidationIssue(
                    "version_evidence_missing",
                    "VersionVector evidence is required",
                    "evidence",
                )
            )
            return
        mappings = (
            ("catalogHash", "catalogHash"),
            ("masterVersion", "masterVersion"),
            ("assetManifestVersion", "assetManifestVersion"),
        )
        for vector_key, evidence_key in mappings:
            if vector.get(vector_key) != evidence.get(evidence_key):
                issues.append(
                    ValidationIssue(
                        "version_evidence_mismatch",
                        f"{vector_key} does not match acquired evidence",
                        f"evidence.{evidence_key}",
                    )
                )

    def _derive_object_evidence(
        self,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        objects = candidate.get("objects")
        if not isinstance(objects, list):
            return result
        for record in objects:
            if not isinstance(record, Mapping):
                continue
            role = record.get("role")
            sha256 = record.get("sha256")
            if (
                not isinstance(sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or not self._store.has_object(sha256)
            ):
                continue
            if role == "assetManifest":
                result["assetManifestVersion"] = sha256
            elif role in {"catalogHash", "masterVersion"}:
                try:
                    with self._store.open_object(sha256) as stream:
                        value = stream.read(1024).decode("utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    continue
                result["catalogHash" if role == "catalogHash" else "masterVersion"] = value
        return result

    def _validate_objects(
        self,
        candidate: Mapping[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        objects = candidate.get("objects")
        if not isinstance(objects, list) or not objects:
            issues.append(
                ValidationIssue(
                    "objects_missing",
                    "release must reference at least one stored object",
                    "objects",
                )
            )
            return
        roles: set[str] = set()
        for index, record in enumerate(objects):
            path = f"objects[{index}]"
            if not isinstance(record, dict):
                issues.append(
                    ValidationIssue(
                        "object_invalid",
                        "object reference must be a mapping",
                        path,
                    )
                )
                continue
            role = record.get("role")
            sha256 = record.get("sha256")
            byte_size = record.get("byteSize")
            if isinstance(role, str):
                roles.add(role)
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                issues.append(
                    ValidationIssue(
                        "object_invalid",
                        "object SHA-256 is invalid",
                        f"{path}.sha256",
                    )
                )
                continue
            if type(byte_size) is not int or byte_size < 0:
                issues.append(
                    ValidationIssue(
                        "object_invalid",
                        "object byte size is invalid",
                        f"{path}.byteSize",
                    )
                )
                continue
            if not self._store.has_object(sha256):
                issues.append(
                    ValidationIssue(
                        "object_missing",
                        "referenced object is absent",
                        path,
                    )
                )
                continue
            metadata = self._store.object_metadata(sha256)
            if metadata.byte_size != byte_size:
                issues.append(
                    ValidationIssue(
                        "object_size_mismatch",
                        "stored object size differs from manifest",
                        path,
                    )
                )
            if _sha256_path(metadata.path) != sha256:
                issues.append(
                    ValidationIssue(
                        "object_hash_mismatch",
                        "stored object content failed SHA-256 verification",
                        path,
                    )
                )
        for required_role in ("catalog", "masterTable"):
            if required_role not in roles:
                issues.append(
                    ValidationIssue(
                        "required_object_role_missing",
                        f"release is missing required object role {required_role}",
                        "objects",
                    )
                )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _critical_rows(manifest: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(manifest, Mapping):
        return {}
    statistics = manifest.get("statistics")
    if not isinstance(statistics, Mapping):
        return {}
    rows = statistics.get("criticalTableRows")
    return rows if isinstance(rows, Mapping) else {}


def _version_value(manifest: Mapping[str, Any] | None, name: str) -> Any:
    if not isinstance(manifest, Mapping):
        return None
    content = manifest.get("contentRelease")
    if not isinstance(content, Mapping):
        return None
    vector = content.get("versionVector")
    return vector.get(name) if isinstance(vector, Mapping) else None
