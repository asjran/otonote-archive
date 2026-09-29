"""Adapter-driven comparison of remote content version vectors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .models import (
    ClientBuild,
    ContentRelease,
    GateReason,
    JobCheckpoint,
    JobStatus,
    VersionVector,
)
from .secrets import SecretUnavailable


@dataclass(frozen=True)
class ProbeObservation:
    version_vector: VersionVector | None
    not_modified: bool = False

    def __post_init__(self) -> None:
        if self.not_modified and self.version_vector is not None:
            raise ValueError("304 observation cannot include a version vector")
        if not self.not_modified and self.version_vector is None:
            raise ValueError("version observation requires a version vector")


class VersionProbeAdapter(Protocol):
    def observe_version(self) -> ProbeObservation:
        ...


@dataclass(frozen=True)
class ProbeResult:
    changes: tuple[str, ...]
    observed_version_vector: VersionVector
    candidate_release: ContentRelease | None
    checkpoint: JobCheckpoint | None


class VersionProbe:
    def __init__(
        self,
        *,
        client_build: ClientBuild,
        previous_release: ContentRelease,
        environment_id: str,
        job_id: str,
    ):
        if (
            previous_release.region != client_build.region
            or previous_release.channel != client_build.channel
        ):
            raise ValueError("previous release and ClientBuild must share server identity")
        self._client_build = client_build
        self._previous_release = previous_release
        self._environment_id = environment_id
        self._job_id = job_id

    def probe(self, adapter: VersionProbeAdapter) -> ProbeResult:
        previous = self._previous_release.version_vector
        try:
            observation = adapter.observe_version()
        except SecretUnavailable:
            return ProbeResult(
                changes=("unknown_change",),
                observed_version_vector=previous,
                candidate_release=None,
                checkpoint=self._gate(
                    JobStatus.NEEDS_AUTH_MATERIAL,
                    "authentication material is missing or expired",
                    "version_probe",
                    None,
                ),
            )
        if observation.not_modified:
            return ProbeResult(
                changes=("unchanged",),
                observed_version_vector=previous,
                candidate_release=None,
                checkpoint=None,
            )

        observed = observation.version_vector
        assert observed is not None
        changes = compare_version_vectors(previous, observed)
        if changes == ("unchanged",):
            return ProbeResult(changes, observed, None, None)

        candidate = ContentRelease.for_client_build(self._client_build, observed)
        checkpoint = None
        if "remote_code_changed" in changes:
            checkpoint = self._gate(
                JobStatus.NEEDS_REMOTE_CODE_REVIEW,
                "remote executable content hash changed",
                "version_probe",
                candidate.id,
            )
        elif "minimum_client_increased" in changes:
            checkpoint = self._gate(
                JobStatus.NEEDS_PACKAGE_REVIEW,
                "minimum supported client version increased",
                "version_probe",
                candidate.id,
            )
        return ProbeResult(changes, observed, candidate, checkpoint)

    def _gate(
        self,
        status: JobStatus,
        summary: str,
        retry_from_stage: str,
        release_ref: str | None,
    ) -> JobCheckpoint:
        return JobCheckpoint(
            job_id=self._job_id,
            environment_id=self._environment_id,
            content_release_ref=release_ref,
            status=status,
            completed_stages=(),
            gate_reason=GateReason(
                code=status.value,
                summary=summary,
                retry_from_stage=retry_from_stage,
            ),
        )


def _version_parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def compare_version_vectors(
    previous: VersionVector,
    observed: VersionVector,
) -> tuple[str, ...]:
    changes: list[str] = []
    mappings = (
        ("master_version", "master_changed"),
        ("catalog_hash", "catalog_changed"),
        ("asset_manifest_version", "assets_changed"),
        ("bootstrap_revision", "bootstrap_changed"),
    )
    for field_name, change_name in mappings:
        before = getattr(previous, field_name)
        after = getattr(observed, field_name)
        if before == after:
            continue
        if before is not None and after is None:
            changes.append("unknown_change")
        else:
            changes.append(change_name)

    if previous.minimum_client_version != observed.minimum_client_version:
        before = previous.minimum_client_version
        after = observed.minimum_client_version
        if after is None:
            changes.append("unknown_change")
        elif before is None or _version_parts(after) > _version_parts(before):
            changes.append("minimum_client_increased")
        else:
            changes.append("unknown_change")

    if previous.remote_code_hash != observed.remote_code_hash:
        if observed.remote_code_hash is None:
            changes.append("unknown_change")
        else:
            changes.append("remote_code_changed")
    if previous.client_version != observed.client_version:
        changes.append("unknown_change")
    if not changes:
        return ("unchanged",)
    return tuple(dict.fromkeys(changes))
