"""Crash-safe orchestration for content acquisition and validation stages."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from .models import Channel, GATE_STATUSES, GateReason, JobCheckpoint, JobStatus, Region
from .release_repository import ReleaseRepository


class PipelineError(RuntimeError):
    """Raised when a pipeline checkpoint or transition is invalid."""


class PipelineGate(RuntimeError):
    """A deliberate manual gate requested by a stage adapter."""

    def __init__(self, status: JobStatus, summary: str):
        if status not in GATE_STATUSES:
            raise ValueError("PipelineGate requires a gate JobStatus")
        if not summary.strip():
            raise ValueError("PipelineGate summary cannot be empty")
        super().__init__(summary)
        self.status = status
        self.summary = summary


class PipelineStage(str, Enum):
    FETCHING_CATALOG = "fetching_catalog"
    FETCHING_MASTER = "fetching_master"
    PLANNING_ASSETS = "planning_assets"
    FETCHING_ASSETS = "fetching_assets"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"


STAGES = tuple(PipelineStage)


@dataclass(frozen=True)
class PipelineContext:
    job_id: str
    environment_id: str
    content_release_ref: str | None
    artifacts: Mapping[str, Any]


@dataclass(frozen=True)
class StageResult:
    artifacts: Mapping[str, Any]
    validated: bool = False


class PipelineAdapter(Protocol):
    def execute(
        self,
        stage: PipelineStage,
        context: PipelineContext,
    ) -> StageResult: ...


@dataclass(frozen=True)
class PipelineResult:
    checkpoint: JobCheckpoint
    artifacts: Mapping[str, Any]
    invalidated: bool = False


@dataclass(frozen=True)
class _StoredCheckpoint:
    checkpoint: JobCheckpoint
    adapter_version: str
    input_fingerprint: str
    artifacts: Mapping[str, Any]


class ContentPipeline:
    def __init__(
        self,
        *,
        data_root: Path,
        adapter_version: str,
        input_fingerprint: str,
    ):
        if not adapter_version.strip():
            raise ValueError("adapter_version cannot be empty")
        if not re.fullmatch(r"[0-9a-f]{64}", input_fingerprint):
            raise ValueError("input_fingerprint must be a SHA-256")
        self._job_root = data_root / "jobs"
        self._adapter_version = adapter_version
        self._input_fingerprint = input_fingerprint

    def run(
        self,
        *,
        job_id: str,
        environment_id: str,
        content_release_ref: str | None,
        adapter: PipelineAdapter,
    ) -> PipelineResult:
        self._validate_identifier(job_id, "job_id")
        if not environment_id.strip():
            raise ValueError("environment_id cannot be empty")
        if self._checkpoint_path(job_id).exists():
            raise PipelineError(f"pipeline job already exists: {job_id}")
        initial = JobCheckpoint(
            job_id=job_id,
            environment_id=environment_id,
            content_release_ref=content_release_ref,
            status=JobStatus.DISCOVERED,
            completed_stages=(),
            gate_reason=None,
        )
        stored = _StoredCheckpoint(
            initial,
            self._adapter_version,
            self._input_fingerprint,
            {},
        )
        self._save(stored)
        return self._execute(stored, adapter, start_index=0)

    def resume(self, *, job_id: str, adapter: PipelineAdapter) -> PipelineResult:
        stored = self._load(job_id)
        if (
            stored.adapter_version != self._adapter_version
            or stored.input_fingerprint != self._input_fingerprint
        ):
            reset = JobCheckpoint(
                job_id=stored.checkpoint.job_id,
                environment_id=stored.checkpoint.environment_id,
                content_release_ref=stored.checkpoint.content_release_ref,
                status=JobStatus.DISCOVERED,
                completed_stages=(),
                gate_reason=None,
            )
            restarted = _StoredCheckpoint(
                reset,
                self._adapter_version,
                self._input_fingerprint,
                {},
            )
            self._save(restarted)
            result = self._execute(restarted, adapter, start_index=0)
            return PipelineResult(
                checkpoint=result.checkpoint,
                artifacts=result.artifacts,
                invalidated=True,
            )
        completed = set(stored.checkpoint.completed_stages)
        start_index = next(
            (index for index, stage in enumerate(STAGES) if stage.value not in completed),
            len(STAGES),
        )
        return self._execute(stored, adapter, start_index=start_index)

    def status(self, job_id: str) -> JobCheckpoint:
        return self._load(job_id).checkpoint

    def publish(
        self,
        *,
        job_id: str,
        repository: ReleaseRepository,
        region: Region,
        channel: Channel,
    ) -> JobCheckpoint:
        stored = self._load(job_id)
        if (
            stored.adapter_version != self._adapter_version
            or stored.input_fingerprint != self._input_fingerprint
        ):
            raise PipelineError("pipeline inputs changed; resume before publishing")
        checkpoint = stored.checkpoint
        if checkpoint.status != JobStatus.READY_FOR_PUBLISH:
            raise PipelineError("pipeline job is not ready for publish")
        if checkpoint.content_release_ref is None:
            raise PipelineError("pipeline job has no candidate release")
        repository.publish_candidate(
            region,
            channel,
            checkpoint.content_release_ref,
        )
        published = JobCheckpoint(
            job_id=checkpoint.job_id,
            environment_id=checkpoint.environment_id,
            content_release_ref=checkpoint.content_release_ref,
            status=JobStatus.PUBLISHED,
            completed_stages=checkpoint.completed_stages,
            gate_reason=None,
        )
        self._save(
            _StoredCheckpoint(
                published,
                stored.adapter_version,
                stored.input_fingerprint,
                stored.artifacts,
            )
        )
        return published

    def _execute(
        self,
        stored: _StoredCheckpoint,
        adapter: PipelineAdapter,
        *,
        start_index: int,
    ) -> PipelineResult:
        checkpoint = stored.checkpoint
        artifacts = dict(stored.artifacts)
        completed = list(checkpoint.completed_stages)
        if start_index >= len(STAGES):
            return PipelineResult(checkpoint, artifacts)

        for index in range(start_index, len(STAGES)):
            stage = STAGES[index]
            in_progress = JobCheckpoint(
                job_id=checkpoint.job_id,
                environment_id=checkpoint.environment_id,
                content_release_ref=checkpoint.content_release_ref,
                status=JobStatus(stage.value),
                completed_stages=tuple(completed),
                gate_reason=None,
            )
            self._save(
                _StoredCheckpoint(
                    in_progress,
                    self._adapter_version,
                    self._input_fingerprint,
                    artifacts,
                )
            )
            try:
                result = adapter.execute(
                    stage,
                    PipelineContext(
                        job_id=in_progress.job_id,
                        environment_id=in_progress.environment_id,
                        content_release_ref=in_progress.content_release_ref,
                        artifacts=dict(artifacts),
                    ),
                )
                if stage == PipelineStage.VALIDATING and not result.validated:
                    raise PipelineGate(
                        JobStatus.VALIDATION_FAILED,
                        "validation stage did not provide successful validation evidence",
                    )
                try:
                    json.dumps(result.artifacts, ensure_ascii=False, sort_keys=True)
                except (TypeError, ValueError):
                    raise PipelineGate(
                        JobStatus.VALIDATION_FAILED,
                        "stage artifacts are not checkpoint-safe JSON values",
                    ) from None
                if _contains_sensitive_material(result.artifacts):
                    raise PipelineGate(
                        JobStatus.VALIDATION_FAILED,
                        "stage artifacts contain secret or device material",
                    )
                artifacts.update(result.artifacts)
            except PipelineGate as gate:
                gated = JobCheckpoint(
                    job_id=in_progress.job_id,
                    environment_id=in_progress.environment_id,
                    content_release_ref=in_progress.content_release_ref,
                    status=gate.status,
                    completed_stages=tuple(completed),
                    gate_reason=GateReason(
                        code=gate.status.value,
                        summary=_safe_gate_summary(gate.summary),
                        retry_from_stage=stage.value,
                    ),
                )
                self._save(
                    _StoredCheckpoint(
                        gated,
                        self._adapter_version,
                        self._input_fingerprint,
                        artifacts,
                    )
                )
                return PipelineResult(gated, artifacts)
            except Exception as error:
                gated = JobCheckpoint(
                    job_id=in_progress.job_id,
                    environment_id=in_progress.environment_id,
                    content_release_ref=in_progress.content_release_ref,
                    status=JobStatus.VALIDATION_FAILED,
                    completed_stages=tuple(completed),
                    gate_reason=GateReason(
                        code=JobStatus.VALIDATION_FAILED.value,
                        summary=f"{type(error).__name__}: stage execution failed",
                        retry_from_stage=stage.value,
                    ),
                )
                self._save(
                    _StoredCheckpoint(
                        gated,
                        self._adapter_version,
                        self._input_fingerprint,
                        artifacts,
                    )
                )
                return PipelineResult(gated, artifacts)

            completed.append(stage.value)
            next_status = (
                JobStatus.READY_FOR_PUBLISH
                if index == len(STAGES) - 1
                else JobStatus(STAGES[index + 1].value)
            )
            checkpoint = JobCheckpoint(
                job_id=in_progress.job_id,
                environment_id=in_progress.environment_id,
                content_release_ref=in_progress.content_release_ref,
                status=next_status,
                completed_stages=tuple(completed),
                gate_reason=None,
            )
            self._save(
                _StoredCheckpoint(
                    checkpoint,
                    self._adapter_version,
                    self._input_fingerprint,
                    artifacts,
                )
            )
        return PipelineResult(checkpoint, artifacts)

    def _checkpoint_path(self, job_id: str) -> Path:
        self._validate_identifier(job_id, "job_id")
        return self._job_root / job_id / "checkpoint.json"

    def _save(self, stored: _StoredCheckpoint) -> None:
        path = self._checkpoint_path(stored.checkpoint.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": 1,
            "adapterVersion": stored.adapter_version,
            "inputFingerprint": stored.input_fingerprint,
            "checkpoint": {
                "jobId": stored.checkpoint.job_id,
                "environmentId": stored.checkpoint.environment_id,
                "contentReleaseRef": stored.checkpoint.content_release_ref,
                "status": stored.checkpoint.status.value,
                "completedStages": list(stored.checkpoint.completed_stages),
                "gateReason": (
                    None
                    if stored.checkpoint.gate_reason is None
                    else {
                        "code": stored.checkpoint.gate_reason.code,
                        "summary": stored.checkpoint.gate_reason.summary,
                        "retryFromStage": stored.checkpoint.gate_reason.retry_from_stage,
                    }
                ),
            },
            "artifacts": dict(stored.artifacts),
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix="checkpoint-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                json.dump(payload, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _load(self, job_id: str) -> _StoredCheckpoint:
        path = self._checkpoint_path(job_id)
        if not path.is_file():
            raise PipelineError(f"pipeline job does not exist: {job_id}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            raw = value["checkpoint"]
            raw_gate = raw["gateReason"]
            gate = (
                None
                if raw_gate is None
                else GateReason(
                    code=raw_gate["code"],
                    summary=raw_gate["summary"],
                    retry_from_stage=raw_gate["retryFromStage"],
                )
            )
            checkpoint = JobCheckpoint(
                job_id=raw["jobId"],
                environment_id=raw["environmentId"],
                content_release_ref=raw["contentReleaseRef"],
                status=JobStatus(raw["status"]),
                completed_stages=tuple(raw["completedStages"]),
                gate_reason=gate,
            )
            return _StoredCheckpoint(
                checkpoint=checkpoint,
                adapter_version=value["adapterVersion"],
                input_fingerprint=value["inputFingerprint"],
                artifacts=value.get("artifacts", {}),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PipelineError(f"invalid pipeline checkpoint: {path}") from error

    @staticmethod
    def _validate_identifier(value: str, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError(f"{name} must be a path-safe identifier")


def _safe_gate_summary(summary: str) -> str:
    sensitive = re.compile(
        r"authorization\s*[:=]|bearer\s+|"
        r"(?:cookie|password|passwd|token|secret|device[-_]?id)\s*[:=]",
        re.IGNORECASE,
    )
    if sensitive.search(summary):
        return "manual gate requested; sensitive details redacted"
    return summary


def _contains_sensitive_material(value: Any) -> bool:
    sensitive_keys = {
        "authorization",
        "cookie",
        "password",
        "passwd",
        "token",
        "secret",
        "deviceid",
        "rawresponse",
        "privateresponse",
    }
    sensitive_value = re.compile(
        r"authorization\s*[:=]|bearer\s+|"
        r"(?:cookie|password|passwd|token|secret|device[-_]?id)\s*[:=]",
        re.IGNORECASE,
    )
    if isinstance(value, Mapping):
        return any(
            re.sub(r"[^a-z0-9]", "", str(key).lower()) in sensitive_keys
            or _contains_sensitive_material(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_material(child) for child in value)
    return isinstance(value, str) and sensitive_value.search(value) is not None
