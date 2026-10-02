"""Stable identities shared by resource pipeline adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping


class Region(str, Enum):
    GLOBAL = "global"
    JP = "jp"


class Channel(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    FETCHING_CATALOG = "fetching_catalog"
    FETCHING_MASTER = "fetching_master"
    PLANNING_ASSETS = "planning_assets"
    FETCHING_ASSETS = "fetching_assets"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"
    READY_FOR_PUBLISH = "ready_for_publish"
    PUBLISHED = "published"
    NEEDS_PACKAGE_REVIEW = "needs_package_review"
    NEEDS_AUTH_MATERIAL = "needs_auth_material"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    UNSUPPORTED_CATALOG_VERSION = "unsupported_catalog_version"
    NEEDS_REMOTE_CODE_REVIEW = "needs_remote_code_review"
    VALIDATION_FAILED = "validation_failed"


GATE_STATUSES = {
    JobStatus.NEEDS_PACKAGE_REVIEW,
    JobStatus.NEEDS_AUTH_MATERIAL,
    JobStatus.UNSUPPORTED_PROTOCOL,
    JobStatus.UNSUPPORTED_CATALOG_VERSION,
    JobStatus.NEEDS_REMOTE_CODE_REVIEW,
    JobStatus.VALIDATION_FAILED,
}


@dataclass(frozen=True)
class GateReason:
    code: str
    summary: str
    retry_from_stage: str

    def __post_init__(self) -> None:
        if self.code not in {status.value for status in GATE_STATUSES}:
            raise ValueError(f"unsupported gate reason: {self.code}")
        if not self.summary.strip():
            raise ValueError("gate reason summary cannot be empty")
        if not self.retry_from_stage.strip():
            raise ValueError("retry_from_stage cannot be empty")


@dataclass(frozen=True)
class JobCheckpoint:
    job_id: str
    environment_id: str
    content_release_ref: str | None
    status: JobStatus
    completed_stages: tuple[str, ...]
    gate_reason: GateReason | None

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.environment_id.strip():
            raise ValueError("checkpoint job and environment IDs cannot be empty")
        if len(set(self.completed_stages)) != len(self.completed_stages):
            raise ValueError("completed_stages cannot contain duplicates")
        if self.status in GATE_STATUSES and self.gate_reason is None:
            raise ValueError(f"{self.status.value} requires a gate_reason")
        if self.status not in GATE_STATUSES and self.gate_reason is not None:
            raise ValueError(f"{self.status.value} cannot include a gate_reason")
        if self.gate_reason is not None and self.gate_reason.code != self.status.value:
            raise ValueError("gate_reason code must match checkpoint status")


@dataclass(frozen=True)
class SourceObject:
    sha256: str
    byte_size: int
    media_type: str
    source_uri: str
    visibility: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        if (
            not isinstance(self.byte_size, int)
            or isinstance(self.byte_size, bool)
            or self.byte_size < 0
        ):
            raise ValueError("byte_size must be a non-negative integer")
        if not self.media_type.strip():
            raise ValueError("media_type cannot be empty")
        if not self.source_uri.strip():
            raise ValueError("source_uri cannot be empty")
        if self.visibility not in {"private", "internal", "public"}:
            raise ValueError("visibility must be private, internal, or public")


@dataclass(frozen=True)
class CanonicalEvidence:
    kind: str
    value: str

    def __post_init__(self) -> None:
        allowed = {
            "explicitMasterKey",
            "matchingAssetSha256",
            "verifiedBusinessFields",
            "manualConfirmation",
        }
        if self.kind not in allowed:
            raise ValueError(f"unsupported evidence kind: {self.kind}")
        if not self.value.strip():
            raise ValueError("evidence value cannot be empty")
        if self.kind == "matchingAssetSha256" and not re.fullmatch(
            r"[0-9a-f]{64}", self.value
        ):
            raise ValueError("matchingAssetSha256 evidence must be a SHA-256")


@dataclass(frozen=True)
class CanonicalEntity:
    id: str
    variant_refs: tuple[str, ...]
    evidence: tuple[CanonicalEvidence, ...]

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("canonical entity id cannot be empty")
        if len(set(self.variant_refs)) < 2:
            raise ValueError("canonical entity requires two distinct variants")
        if not self.evidence:
            raise ValueError("canonical entity evidence cannot be empty")


@dataclass(frozen=True)
class ClientBuild:
    region: Region
    channel: Channel
    platform: str
    package_name: str
    version_name: str
    version_code: int
    package_sha256: str
    unity_version: str
    client_generation: str
    auth_profile_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "platform",
            "package_name",
            "version_name",
            "unity_version",
            "client_generation",
            "auth_profile_ref",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", self.platform):
            raise ValueError("platform must be a path-safe lowercase identifier")
        if type(self.version_code) is not int or self.version_code <= 0:
            raise ValueError("version_code must be a positive integer")
        if not re.fullmatch(r"[0-9a-f]{64}", self.package_sha256):
            raise ValueError("package_sha256 must be 64 lowercase hex characters")

    @property
    def id(self) -> str:
        return (
            f"{self.region.value}-{self.channel.value}-{self.platform}-"
            f"{self.version_code}-{self.package_sha256[:16]}"
        )


@dataclass(frozen=True)
class VersionVector:
    client_version: str
    minimum_client_version: str | None
    bootstrap_revision: str | None
    catalog_hash: str | None
    master_version: str | None
    asset_manifest_version: str | None
    remote_code_hash: str | None

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if value is None:
                if field_name == "client_version":
                    raise ValueError("client_version cannot be unknown")
                continue
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

    def as_canonical_dict(self) -> dict[str, str | None]:
        values = asdict(self)
        return {
            "assetManifestVersion": values["asset_manifest_version"],
            "bootstrapRevision": values["bootstrap_revision"],
            "catalogHash": values["catalog_hash"],
            "clientVersion": values["client_version"],
            "masterVersion": values["master_version"],
            "minimumClientVersion": values["minimum_client_version"],
            "remoteCodeHash": values["remote_code_hash"],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.as_canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ContentRelease:
    region: Region
    channel: Channel
    observed_by_client_build_ref: str
    version_vector: VersionVector

    @classmethod
    def for_client_build(
        cls,
        client_build: ClientBuild,
        version_vector: VersionVector,
    ) -> "ContentRelease":
        return cls(
            region=client_build.region,
            channel=client_build.channel,
            observed_by_client_build_ref=client_build.id,
            version_vector=version_vector,
        )

    @property
    def id(self) -> str:
        return content_release_id(self.region, self.channel, self.version_vector)


@dataclass(frozen=True)
class EntityVariant:
    entity_type: str
    region: Region
    channel: Channel
    source_master_id: str
    first_seen_content_release: str
    last_seen_content_release: str
    availability: str
    localized_text: tuple[tuple[str, str], ...]
    asset_relations: tuple[str, ...] = ()
    source_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "entity_type",
            "source_master_id",
            "first_seen_content_release",
            "last_seen_content_release",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        if self.availability not in {
            "available",
            "planned",
            "ended",
            "historical",
            "unknown",
        }:
            raise ValueError("unsupported availability")
        allowed_locales = {"zh-CN", "zh-TW", "ja", "en"}
        locale_names = [locale for locale, _ in self.localized_text]
        if len(locale_names) != len(set(locale_names)):
            raise ValueError("localized_text contains duplicate locales")
        for locale, value in self.localized_text:
            if locale not in allowed_locales:
                raise ValueError(f"unsupported locale: {locale}")
            if not value.strip():
                raise ValueError(f"localized text for {locale} cannot be empty")

    @classmethod
    def for_release(
        cls,
        release: ContentRelease,
        *,
        entity_type: str,
        source_master_id: str,
        availability: str,
        localized_text: Mapping[str, str],
    ) -> "EntityVariant":
        return cls(
            entity_type=entity_type,
            region=release.region,
            channel=release.channel,
            source_master_id=source_master_id,
            first_seen_content_release=release.id,
            last_seen_content_release=release.id,
            availability=availability,
            localized_text=tuple(sorted(localized_text.items())),
        )

    def localized_text_dict(self) -> dict[str, str]:
        return dict(self.localized_text)


def content_release_id(
    region: Region,
    channel: Channel,
    version_vector: VersionVector,
) -> str:
    return f"{region.value}-{channel.value}-{version_vector.fingerprint()[:16]}"
