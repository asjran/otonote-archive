"""Environment-bound source replay seam for offline protocol development."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .config import EnvironmentConfig
from .models import VersionVector
from .pipeline import PipelineContext, PipelineStage, StageResult
from .version_probe import ProbeObservation


class SourceReplayError(ValueError):
    """Raised when replay evidence is unsafe or belongs to another environment."""


@dataclass(frozen=True)
class SourceEvidence:
    environment_id: str
    server_identity: str
    source_status: str
    fixture_name: str


@dataclass(frozen=True)
class ReplayAsset:
    primary_key: str
    source_uri: str
    expected_sha256: str
    expected_size: int


class SourceAdapter(Protocol):
    @property
    def version_vector(self) -> VersionVector: ...

    def observe_version(self) -> ProbeObservation: ...

    def fetch_catalog(self) -> dict[str, Any]: ...

    def fetch_master(self) -> dict[str, Any]: ...

    def plan_assets(self) -> tuple[ReplayAsset, ...]: ...

    def source_evidence(self) -> SourceEvidence: ...


class ReplaySourceAdapter:
    """Replay one sanitized source observation through the production seam."""

    source_status = "offline_replay"

    def __init__(
        self,
        *,
        environment: EnvironmentConfig,
        fixture_path: Path,
        value: Mapping[str, Any],
    ):
        self._environment = environment
        self._fixture_path = fixture_path
        self._value = dict(value)
        self._vector = _version_vector(self._object("versionVector"))
        catalog_hash = self._object("catalog").get("catalogHash")
        if catalog_hash != self._vector.catalog_hash:
            raise SourceReplayError("Catalog version mismatch in source replay")
        master_version = self._object("master").get("masterVersion")
        if master_version != self._vector.master_version:
            raise SourceReplayError("Master version mismatch in source replay")

    @classmethod
    def from_fixture(
        cls,
        path: Path,
        *,
        environment: EnvironmentConfig,
    ) -> "ReplaySourceAdapter":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceReplayError("source replay fixture is unreadable") from exc
        if not isinstance(value, dict):
            raise SourceReplayError("source replay fixture must be an object")
        _reject_sensitive_fields(value)
        if value.get("schemaVersion") != 1:
            raise SourceReplayError("unsupported source replay schemaVersion")
        identity = value.get("identity")
        if not isinstance(identity, dict):
            raise SourceReplayError("source replay identity is missing")
        expected = {
            "environmentId": environment.environment_id,
            "region": environment.region.value,
            "channel": environment.channel.value,
            "clientBuildRef": environment.client_build_ref,
        }
        for key, expected_value in expected.items():
            if identity.get(key) != expected_value:
                raise SourceReplayError(
                    f"source replay {key} does not match environment"
                )
        return cls(environment=environment, fixture_path=path, value=value)

    def observe_version(self) -> ProbeObservation:
        return ProbeObservation(version_vector=self._vector)

    @property
    def version_vector(self) -> VersionVector:
        return self._vector

    def fetch_catalog(self) -> dict[str, Any]:
        return dict(self._object("catalog"))

    def fetch_master(self) -> dict[str, Any]:
        return dict(self._object("master"))

    def plan_assets(self) -> tuple[ReplayAsset, ...]:
        raw_assets = self._value.get("assets")
        if not isinstance(raw_assets, list):
            raise SourceReplayError("source replay assets must be an array")
        assets: list[ReplayAsset] = []
        for raw in raw_assets:
            if not isinstance(raw, dict):
                raise SourceReplayError("source replay asset must be an object")
            primary_key = raw.get("primaryKey")
            source_uri = raw.get("sourceUri")
            expected_sha256 = raw.get("sha256")
            expected_size = raw.get("byteSize")
            if not isinstance(primary_key, str) or not primary_key.strip():
                raise SourceReplayError("source replay asset primaryKey is invalid")
            if not isinstance(source_uri, str) or not source_uri.startswith("fixture://"):
                raise SourceReplayError("source replay asset must use fixture://")
            if not isinstance(expected_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_sha256
            ):
                raise SourceReplayError("source replay asset sha256 is invalid")
            if type(expected_size) is not int or expected_size < 0:
                raise SourceReplayError("source replay asset byteSize is invalid")
            assets.append(
                ReplayAsset(
                    primary_key=primary_key,
                    source_uri=source_uri,
                    expected_sha256=expected_sha256,
                    expected_size=expected_size,
                )
            )
        return tuple(assets)

    def source_evidence(self) -> SourceEvidence:
        return SourceEvidence(
            environment_id=self._environment.environment_id,
            server_identity=(
                f"{self._environment.region.value}/"
                f"{self._environment.channel.value}"
            ),
            source_status=self.source_status,
            fixture_name=self._fixture_path.name,
        )

    def _object(self, name: str) -> Mapping[str, Any]:
        value = self._value.get(name)
        if not isinstance(value, dict):
            raise SourceReplayError(f"source replay {name} must be an object")
        return value


class ReplayPipelineAdapter:
    """Drive the recoverable pipeline from one sanitized replay source."""

    def __init__(self, source: ReplaySourceAdapter):
        self._source = source

    def execute(
        self,
        stage: PipelineStage,
        context: PipelineContext,
    ) -> StageResult:
        evidence = self._source.source_evidence()
        if context.environment_id != evidence.environment_id:
            raise SourceReplayError(
                "pipeline environment does not match source replay"
            )
        if stage == PipelineStage.FETCHING_CATALOG:
            return StageResult(
                {
                    "catalog": self._source.fetch_catalog(),
                    "sourceEvidence": {
                        "environmentId": evidence.environment_id,
                        "fixtureName": evidence.fixture_name,
                        "serverIdentity": evidence.server_identity,
                        "sourceStatus": evidence.source_status,
                    },
                }
            )
        if stage == PipelineStage.FETCHING_MASTER:
            return StageResult({"master": self._source.fetch_master()})
        if stage == PipelineStage.PLANNING_ASSETS:
            return StageResult(
                {
                    "assetPlan": [
                        {
                            "byteSize": item.expected_size,
                            "primaryKey": item.primary_key,
                            "sha256": item.expected_sha256,
                            "sourceUri": item.source_uri,
                        }
                        for item in self._source.plan_assets()
                    ]
                }
            )
        if stage == PipelineStage.FETCHING_ASSETS:
            return StageResult({"acquiredAssets": []})
        if stage == PipelineStage.NORMALIZING:
            return StageResult(
                {
                    "normalizedSource": {
                        "environmentId": evidence.environment_id,
                        "versionVectorHash": self._source.version_vector.fingerprint(),
                    }
                }
            )
        if stage == PipelineStage.VALIDATING:
            return StageResult(
                {
                    "validationEvidence": {
                        "sourceStatus": evidence.source_status,
                        "status": "valid",
                    }
                },
                validated=True,
            )
        raise AssertionError(f"unsupported pipeline stage: {stage.value}")


def _version_vector(value: Mapping[str, Any]) -> VersionVector:
    try:
        return VersionVector(
            client_version=value["clientVersion"],
            minimum_client_version=value.get("minimumClientVersion"),
            bootstrap_revision=value.get("bootstrapRevision"),
            catalog_hash=value.get("catalogHash"),
            master_version=value.get("masterVersion"),
            asset_manifest_version=value.get("assetManifestVersion"),
            remote_code_hash=value.get("remoteCodeHash"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceReplayError("source replay versionVector is invalid") from exc


def _reject_sensitive_fields(value: Any) -> None:
    sensitive = (
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "deviceid",
        "device-id",
    )
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("_", "")
            if any(fragment.replace("-", "") in normalized for fragment in sensitive):
                raise SourceReplayError("source replay contains sensitive fields")
            _reject_sensitive_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_fields(child)
