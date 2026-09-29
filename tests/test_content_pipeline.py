from __future__ import annotations

import sys
import tempfile
import unittest
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.models import JobStatus  # noqa: E402
from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    Region,
    VersionVector,
)
from tools.resource_pipeline.pipeline import (  # noqa: E402
    ContentPipeline,
    PipelineContext,
    PipelineGate,
    PipelineStage,
    StageResult,
    PipelineError,
)
from tools.resource_pipeline.release_repository import ReleaseRepository  # noqa: E402
from tools.resource_pipeline.cli import main as pipeline_cli  # noqa: E402


class _RecordingAdapter:
    def __init__(self, fail_once_at: PipelineStage | None = None):
        self.fail_once_at = fail_once_at
        self.calls: list[PipelineStage] = []

    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        self.calls.append(stage)
        if self.fail_once_at == stage:
            self.fail_once_at = None
            raise RuntimeError("injected stage interruption")
        return StageResult(
            {f"{stage.value}Artifact": stage.value},
            validated=stage == PipelineStage.VALIDATING,
        )


class _GatedAdapter(_RecordingAdapter):
    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        if stage == PipelineStage.FETCHING_CATALOG:
            raise PipelineGate(
                JobStatus.UNSUPPORTED_CATALOG_VERSION,
                "catalog schema needs a new parser",
            )
        return super().execute(stage, context)


class _UnvalidatedAdapter(_RecordingAdapter):
    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        self.calls.append(stage)
        return StageResult({})


class _SecretGateAdapter(_RecordingAdapter):
    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        raise PipelineGate(
            JobStatus.NEEDS_AUTH_MATERIAL,
            "Authorization: Bearer checkpoint-super-secret",
        )


class _SecretArtifactAdapter(_RecordingAdapter):
    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        return StageResult(
            {"authorization": "Bearer artifact-super-secret"},
            validated=stage == PipelineStage.VALIDATING,
        )


class _NonJsonArtifactAdapter(_RecordingAdapter):
    def execute(self, stage: PipelineStage, context: PipelineContext) -> StageResult:
        return StageResult(
            {"localPath": Path("not-checkpoint-safe")},
            validated=stage == PipelineStage.VALIDATING,
        )


class ContentPipelineTest(unittest.TestCase):
    @staticmethod
    def _release(catalog_hash: str) -> ContentRelease:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.staging",
            version_name="1.0.0",
            version_code=1,
            package_sha256="a" * 64,
            unity_version="6000.3.12f1",
            client_generation="fixture-v1",
            auth_profile_ref="fixture-auth",
        )
        return ContentRelease.for_client_build(
            build,
            VersionVector(
                client_version="1.0.0+1",
                minimum_client_version=None,
                bootstrap_revision=None,
                catalog_hash=catalog_hash,
                master_version="master-v1",
                asset_manifest_version=None,
                remote_code_hash=None,
            ),
        )

    def test_interrupted_stage_resumes_after_last_completed_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pipeline = ContentPipeline(
                data_root=Path(temporary),
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            )
            adapter = _RecordingAdapter(PipelineStage.FETCHING_MASTER)

            interrupted = pipeline.run(
                job_id="job-resume",
                environment_id="global-staging",
                content_release_ref="global-staging-candidate",
                adapter=adapter,
            )

            self.assertEqual(interrupted.checkpoint.status, JobStatus.VALIDATION_FAILED)
            self.assertEqual(
                interrupted.checkpoint.completed_stages,
                (PipelineStage.FETCHING_CATALOG.value,),
            )
            self.assertEqual(
                interrupted.checkpoint.gate_reason.retry_from_stage,
                PipelineStage.FETCHING_MASTER.value,
            )

            completed = pipeline.resume(job_id="job-resume", adapter=adapter)

            self.assertEqual(completed.checkpoint.status, JobStatus.READY_FOR_PUBLISH)
            self.assertEqual(
                adapter.calls.count(PipelineStage.FETCHING_CATALOG),
                1,
            )
            self.assertEqual(pipeline.status("job-resume"), completed.checkpoint)

    def test_changed_adapter_or_input_invalidates_unsafe_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = ContentPipeline(
                data_root=root,
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            )
            first.run(
                job_id="job-invalidated",
                environment_id="global-staging",
                content_release_ref="global-staging-candidate",
                adapter=_RecordingAdapter(PipelineStage.FETCHING_MASTER),
            )
            replacement_adapter = _RecordingAdapter()
            changed = ContentPipeline(
                data_root=root,
                adapter_version="fixture-adapter-v2",
                input_fingerprint="b" * 64,
            )

            result = changed.resume(
                job_id="job-invalidated",
                adapter=replacement_adapter,
            )

            self.assertTrue(result.invalidated)
            self.assertEqual(result.checkpoint.status, JobStatus.READY_FOR_PUBLISH)
            self.assertEqual(
                replacement_adapter.calls[0],
                PipelineStage.FETCHING_CATALOG,
            )

    def test_adapter_can_stop_at_a_specific_manual_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = ContentPipeline(
                data_root=Path(temporary),
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            ).run(
                job_id="job-gated",
                environment_id="global-staging",
                content_release_ref="global-staging-candidate",
                adapter=_GatedAdapter(),
            )

            self.assertEqual(
                result.checkpoint.status,
                JobStatus.UNSUPPORTED_CATALOG_VERSION,
            )
            self.assertEqual(
                result.checkpoint.gate_reason.retry_from_stage,
                PipelineStage.FETCHING_CATALOG.value,
            )

    def test_ready_state_requires_explicit_successful_validation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = ContentPipeline(
                data_root=Path(temporary),
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            ).run(
                job_id="job-unvalidated",
                environment_id="global-staging",
                content_release_ref="global-staging-candidate",
                adapter=_UnvalidatedAdapter(),
            )

        self.assertEqual(result.checkpoint.status, JobStatus.VALIDATION_FAILED)
        self.assertEqual(
            result.checkpoint.gate_reason.retry_from_stage,
            PipelineStage.VALIDATING.value,
        )

    def test_checkpoint_redacts_secret_material_from_gate_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = ContentPipeline(
                data_root=root,
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            ).run(
                job_id="job-secret-gate",
                environment_id="global-staging",
                content_release_ref=None,
                adapter=_SecretGateAdapter(),
            )
            checkpoint_text = (
                root / "jobs/job-secret-gate/checkpoint.json"
            ).read_text(encoding="utf-8")

        self.assertEqual(result.checkpoint.status, JobStatus.NEEDS_AUTH_MATERIAL)
        self.assertNotIn("checkpoint-super-secret", checkpoint_text)
        self.assertNotIn("checkpoint-super-secret", repr(result))

    def test_checkpoint_rejects_secret_bearing_stage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = ContentPipeline(
                data_root=root,
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            ).run(
                job_id="job-secret-artifact",
                environment_id="global-staging",
                content_release_ref=None,
                adapter=_SecretArtifactAdapter(),
            )
            checkpoint_text = (
                root / "jobs/job-secret-artifact/checkpoint.json"
            ).read_text(encoding="utf-8")

        self.assertEqual(result.checkpoint.status, JobStatus.VALIDATION_FAILED)
        self.assertNotIn("artifact-super-secret", checkpoint_text)

    def test_checkpoint_rejects_non_json_stage_artifacts_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = ContentPipeline(
                data_root=Path(temporary),
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            ).run(
                job_id="job-non-json",
                environment_id="global-staging",
                content_release_ref=None,
                adapter=_NonJsonArtifactAdapter(),
            )

        self.assertEqual(result.checkpoint.status, JobStatus.VALIDATION_FAILED)

    def test_failed_candidate_cannot_move_current_then_publishes_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root)
            current = self._release("catalog-v1")
            candidate = self._release("catalog-v2")
            repository.create_candidate(current, {"objects": []})
            repository.create_candidate(candidate, {"objects": []})
            repository.publish_candidate(Region.GLOBAL, Channel.STAGING, current.id)
            pipeline = ContentPipeline(
                data_root=root,
                adapter_version="fixture-adapter-v1",
                input_fingerprint="a" * 64,
            )
            interrupted_adapter = _RecordingAdapter(PipelineStage.VALIDATING)
            pipeline.run(
                job_id="job-publish",
                environment_id="global-staging",
                content_release_ref=candidate.id,
                adapter=interrupted_adapter,
            )

            with self.assertRaises(PipelineError):
                pipeline.publish(
                    job_id="job-publish",
                    repository=repository,
                    region=Region.GLOBAL,
                    channel=Channel.STAGING,
                )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                current.id,
            )

            pipeline.resume(job_id="job-publish", adapter=interrupted_adapter)
            published = pipeline.publish(
                job_id="job-publish",
                repository=repository,
                region=Region.GLOBAL,
                channel=Channel.STAGING,
            )

            self.assertEqual(published.status, JobStatus.PUBLISHED)
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                candidate.id,
            )




if __name__ == "__main__":
    unittest.main()
