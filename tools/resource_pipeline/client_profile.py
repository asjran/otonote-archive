"""Secret-safe structural profiles for detecting client-generation changes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence


CRITICAL_TYPE_ADAPTERS: dict[str, tuple[str, ...]] = {
    "App.Config.NetworkConfig": ("version_probe", "transport"),
    "App.GameLoop.AppCatalogHandler": ("catalog", "asset"),
    "Fwk.Master.MasterDataManager": ("master",),
    "Fwk.AssetDownload.AssetDownloadManager": ("asset",),
    "Fwk.Server.AuthenticatedCallInvoker": ("transport", "version_probe"),
}


@dataclass(frozen=True)
class MethodStructure:
    type_name: str
    method_name: str
    parameter_count: int
    token: int
    assembly: str
    native_address: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("type_name", "method_name", "assembly"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if type(self.parameter_count) is not int or self.parameter_count < 0:
            raise ValueError("parameter_count must be a non-negative integer")
        if type(self.token) is not int or self.token <= 0:
            raise ValueError("token must be a positive integer")
        if self.native_address is not None and (
            type(self.native_address) is not int or self.native_address < 0
        ):
            raise ValueError("native_address must be a non-negative integer or None")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MethodStructure":
        return cls(
            type_name=value["typeName"],
            method_name=value["methodName"],
            parameter_count=value["parameterCount"],
            token=value["token"],
            assembly=value["assembly"],
            native_address=value.get("address"),
        )

    def with_native_address(self, value: int | None) -> "MethodStructure":
        return replace(self, native_address=value)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "assembly": self.assembly,
            "methodName": self.method_name,
            "parameterCount": self.parameter_count,
            "token": self.token,
            "typeName": self.type_name,
        }


@dataclass(frozen=True)
class ClientProfile:
    package_name: str
    package_signature_sha256: str
    unity_version: str
    metadata_version: int
    abi: str
    methods: tuple[MethodStructure, ...]
    constant_hashes: tuple[tuple[str, str], ...]
    protocol_services: tuple[tuple[str, tuple[str, ...]], ...]
    structure_fingerprint: str
    analysis_status: str = "supported"
    package_set_sha256: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "analysisStatus": self.analysis_status,
            "client": {
                "abi": self.abi,
                "metadataVersion": self.metadata_version,
                "packageName": self.package_name,
                "packageSignatureSha256": self.package_signature_sha256,
                "unityVersion": self.unity_version,
            },
            "criticalMethods": [method.canonical_dict() for method in self.methods],
            "criticalConstantHashes": dict(self.constant_hashes),
            "protocolServices": {
                name: list(methods) for name, methods in self.protocol_services
            },
            "structureFingerprint": self.structure_fingerprint,
            "packageSetSha256": self.package_set_sha256,
        }


@dataclass(frozen=True)
class CompatibilityReport:
    classification: str
    affected_adapters: tuple[str, ...]
    changes: tuple[str, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "affectedAdapters": list(self.affected_adapters),
            "changes": list(self.changes),
        }


class ClientProfileBuilder:
    def __init__(
        self,
        *,
        package_name: str,
        package_signature_sha256: str,
        unity_version: str,
        metadata_version: int,
        abi: str,
    ):
        for field_name, value in (
            ("package_name", package_name),
            ("unity_version", unity_version),
            ("abi", abi),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not re.fullmatch(r"[0-9a-f]{64}", package_signature_sha256):
            raise ValueError("package_signature_sha256 must be a SHA-256")
        if type(metadata_version) is not int or metadata_version <= 0:
            raise ValueError("metadata_version must be a positive integer")
        self._package_name = package_name
        self._package_signature_sha256 = package_signature_sha256
        self._unity_version = unity_version
        self._metadata_version = metadata_version
        self._abi = abi

    def build(
        self,
        *,
        methods: Sequence[MethodStructure],
        sensitive_constants: Mapping[str, str | bytes],
        protocol_services: Mapping[str, Sequence[str]] | None = None,
    ) -> ClientProfile:
        if any(not isinstance(name, str) or not name.strip() for name in sensitive_constants):
            raise ValueError("sensitive constant labels cannot be empty")
        for service_name, method_names in (protocol_services or {}).items():
            if not isinstance(service_name, str) or not service_name.strip():
                raise ValueError("protocol service names cannot be empty")
            if any(
                not isinstance(method_name, str) or not method_name.strip()
                for method_name in method_names
            ):
                raise ValueError("protocol method names cannot be empty")
        critical_methods = tuple(
            sorted(
                (
                    method
                    for method in methods
                    if method.type_name in CRITICAL_TYPE_ADAPTERS
                ),
                key=lambda item: (
                    item.type_name,
                    item.method_name,
                    item.parameter_count,
                    item.token,
                    item.assembly,
                ),
            )
        )
        constant_hashes = tuple(
            sorted(
                (
                    name,
                    hashlib.sha256(
                        value if isinstance(value, bytes) else value.encode("utf-8")
                    ).hexdigest(),
                )
                for name, value in sensitive_constants.items()
            )
        )
        services = tuple(
            sorted(
                (name, tuple(sorted(set(methods))))
                for name, methods in (protocol_services or {}).items()
            )
        )
        fingerprint_payload = {
            "criticalConstantHashes": dict(constant_hashes),
            "criticalMethods": [
                method.canonical_dict() for method in critical_methods
            ],
            "protocolServices": {
                name: list(methods) for name, methods in services
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ClientProfile(
            package_name=self._package_name,
            package_signature_sha256=self._package_signature_sha256,
            unity_version=self._unity_version,
            metadata_version=self._metadata_version,
            abi=self._abi,
            methods=critical_methods,
            constant_hashes=constant_hashes,
            protocol_services=services,
            structure_fingerprint=fingerprint,
        )

    def build_from_il2cpp(
        self,
        *,
        metadata_path: Path,
        binary_path: Path,
        code_registration: int,
        sensitive_constants: Mapping[str, str | bytes],
        protocol_services: Mapping[str, Sequence[str]] | None = None,
    ) -> ClientProfile:
        from analysis.crypto.inspect_il2cpp import inspect_method_structures

        records = inspect_method_structures(
            metadata_path,
            binary_path,
            code_registration,
            included_types=set(CRITICAL_TYPE_ADAPTERS),
        )
        return self.build(
            methods=[
                MethodStructure.from_mapping(record.to_dict()) for record in records
            ],
            sensitive_constants=sensitive_constants,
            protocol_services=protocol_services,
        )


def compare_client_profiles(
    previous: ClientProfile,
    candidate: ClientProfile,
) -> CompatibilityReport:
    if (
        previous.analysis_status != "supported"
        or candidate.analysis_status != "supported"
        or previous.metadata_version != candidate.metadata_version
    ):
        return CompatibilityReport(
            classification="unsupported",
            affected_adapters=tuple(
                sorted(
                    {
                        adapter
                        for adapters in CRITICAL_TYPE_ADAPTERS.values()
                        for adapter in adapters
                    }
                )
            ),
            changes=("IL2CPP metadata analysis format changed or is unsupported",),
        )

    if previous.structure_fingerprint == candidate.structure_fingerprint:
        return CompatibilityReport(
            classification="compatible",
            affected_adapters=(),
            changes=(),
        )

    previous_by_type: dict[str, set[tuple[Any, ...]]] = {}
    candidate_by_type: dict[str, set[tuple[Any, ...]]] = {}
    for destination, methods in (
        (previous_by_type, previous.methods),
        (candidate_by_type, candidate.methods),
    ):
        for method in methods:
            destination.setdefault(method.type_name, set()).add(
                (
                    method.method_name,
                    method.parameter_count,
                    method.token,
                    method.assembly,
                )
            )

    changed_types = {
        type_name
        for type_name in CRITICAL_TYPE_ADAPTERS
        if previous_by_type.get(type_name, set())
        != candidate_by_type.get(type_name, set())
    }
    changes = [f"critical method structure changed: {name}" for name in changed_types]
    affected = {
        adapter
        for type_name in changed_types
        for adapter in CRITICAL_TYPE_ADAPTERS[type_name]
    }
    if previous.constant_hashes != candidate.constant_hashes:
        changes.append("critical constant sources changed")
        affected.update(
            adapter
            for adapters in CRITICAL_TYPE_ADAPTERS.values()
            for adapter in adapters
        )
    if previous.protocol_services != candidate.protocol_services:
        changes.append("protobuf or gRPC service summary changed")
        affected.update(("transport", "version_probe"))
    return CompatibilityReport(
        classification="review_required",
        affected_adapters=tuple(sorted(affected)),
        changes=tuple(sorted(changes)),
    )
