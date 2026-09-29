"""Command line entry point for the resource pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

from .config import EnvironmentConfig, load_environment_config, load_platform_config
from .environment_registry import EnvironmentRegistry
from .golden import GoldenInputs, GoldenRegistry, inspect_apk_client_facts
from .package_intake import aggregate_asset_manifests, build_client_profile, build_package_set_manifest
from .models import (
    Channel,
    ClientBuild,
    ContentRelease,
    JobCheckpoint,
    JobStatus,
    Region,
    VersionVector,
)
from .object_store import FileObjectStore
from .pipeline import (
    ContentPipeline,
    PipelineContext,
    PipelineError,
    PipelineGate,
    PipelineStage,
    StageResult,
)
from .release_repository import ReleaseRepository
from .scheduler import EnvironmentScheduler
from .source_adapter import ReplayPipelineAdapter, ReplaySourceAdapter
from .validation import ContentValidator
from .version_probe import VersionProbe


REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _registry(arguments: argparse.Namespace) -> GoldenRegistry:
    return GoldenRegistry(
        data_root=_path(arguments.data_root),
        baseline_path=_path(arguments.baseline),
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _inspect_package_set(arguments: argparse.Namespace) -> int:
    manifest = build_package_set_manifest(_path(arguments.apk_root), region=arguments.region, channel=arguments.channel)
    _write_json(_path(arguments.output), manifest)
    print(json.dumps({"packageSetSha256": manifest["packageSetSha256"], "splitCount": len(manifest["splits"])}, sort_keys=True))
    return 0


def _build_client_profile(arguments: argparse.Namespace) -> int:
    package_set = json.loads(_path(arguments.package_set).read_text(encoding="utf-8"))
    profile = build_client_profile(package_set, methods_path=_path(arguments.methods), metadata_version=arguments.metadata_version, abi=arguments.abi)
    public = profile.to_public_dict()
    public["identity"] = package_set["identity"]
    _write_json(_path(arguments.private_output), public)
    _write_json(_path(arguments.public_output), public)
    print(json.dumps({"analysisStatus": profile.analysis_status, "structureFingerprint": profile.structure_fingerprint}, sort_keys=True))
    return 0


def _aggregate_assets(arguments: argparse.Namespace) -> int:
    catalog_sha = hashlib.sha256(_path(arguments.catalog).read_bytes()).hexdigest()
    value = aggregate_asset_manifests(_path(arguments.bundle_root), catalog_sha256=catalog_sha)
    _write_json(_path(arguments.output), value)
    print(json.dumps({"assetCount": len(value["assets"]), "sourceManifestCount": value["sourceManifestCount"]}, sort_keys=True))
    return 0


def _environment_path(environment_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", environment_id):
        raise ValueError("environment must be a path-safe lowercase identifier")
    return REPO_ROOT / "config/environments" / f"{environment_id}.toml"


def _register(arguments: argparse.Namespace) -> int:
    inputs = GoldenInputs(
        apk=_path(arguments.apk),
        il2cpp=_path(arguments.il2cpp),
        metadata=_path(arguments.metadata),
        catalog=_path(arguments.catalog),
        catalog_hash=_path(arguments.catalog_hash),
        master_version=_path(arguments.master_version),
        master_root=_path(arguments.master_root),
        asset_manifest=_path(arguments.asset_manifest),
        package_set_manifest=(None if arguments.package_set_manifest is None else _path(arguments.package_set_manifest)),
        client_profile=(None if arguments.client_profile is None else _path(arguments.client_profile)),
    )
    client = inspect_apk_client_facts(
        inputs.apk,
        metadata_version=arguments.metadata_version,
        auth_profile_ref=arguments.auth_profile_ref,
    )
    result = _registry(arguments).register(
        region=Region(arguments.region),
        channel=Channel(arguments.channel),
        inputs=inputs,
        client=client,
    )
    if getattr(arguments, "private_manifest_output", None):
        baseline_value = json.loads(result.baseline_path.read_text(encoding="utf-8"))
        _write_json(_path(arguments.private_manifest_output), baseline_value)
    print(
        json.dumps(
            {
                "clientBuildId": result.client_build_id,
                "contentReleaseId": result.content_release_id,
                "archivedObjectCount": result.archived_object_count,
                "baseline": _display_path(result.baseline_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _verify(arguments: argparse.Namespace) -> int:
    result = _registry(arguments).verify()
    if getattr(arguments, "private_manifest_output", None):
        baseline_path = _path(arguments.baseline)
        _write_json(
            _path(arguments.private_manifest_output),
            json.loads(baseline_path.read_text(encoding="utf-8")),
        )
    print(
        json.dumps(
            {
                "clientBuildId": result.client_build_id,
                "contentReleaseId": result.content_release_id,
                "verifiedObjectCount": result.verified_object_count,
                "status": "verified",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _version_vector(value: dict[str, object]) -> VersionVector:
    return VersionVector(
        client_version=value["clientVersion"],  # type: ignore[arg-type]
        minimum_client_version=value["minimumClientVersion"],  # type: ignore[arg-type]
        bootstrap_revision=value["bootstrapRevision"],  # type: ignore[arg-type]
        catalog_hash=value["catalogHash"],  # type: ignore[arg-type]
        master_version=value["masterVersion"],  # type: ignore[arg-type]
        asset_manifest_version=value["assetManifestVersion"],  # type: ignore[arg-type]
        remote_code_hash=value["remoteCodeHash"],  # type: ignore[arg-type]
    )


def _probe_baseline(
    environment: EnvironmentConfig,
    baseline_path: Path,
) -> tuple[ClientBuild, ContentRelease]:
    baseline = json.loads(
        baseline_path.read_text(encoding="utf-8")
    )
    client_value = baseline["client"]
    build = ClientBuild(
        region=environment.region,
        channel=environment.channel,
        platform="android",
        package_name=client_value["packageName"],
        version_name=client_value["versionName"],
        version_code=client_value["versionCode"],
        package_sha256=baseline["objects"]["apk"]["sha256"],
        unity_version=client_value["unityVersion"],
        client_generation=client_value["clientGeneration"],
        auth_profile_ref=environment.auth_profile_ref,
    )
    if build.id != environment.client_build_ref:
        raise ValueError("environment ClientBuild does not match Golden baseline")
    previous = ContentRelease.for_client_build(
        build,
        _version_vector(baseline["versionVector"]),
    )
    return build, previous


def _probe(arguments: argparse.Namespace) -> int:
    environment = load_environment_config(_environment_path(arguments.environment))
    print(json.dumps({"environmentId": environment.environment_id,
                      "status": "unsupported_protocol"}, sort_keys=True))
    return 2


def _pipeline_inputs_for_environment(
    *,
    environment_path: Path,
    baseline_path: Path,
    data_root: Path,
) -> tuple[ContentPipeline, EnvironmentConfig, dict[str, Any]]:
    environment = load_environment_config(environment_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    fingerprint = hashlib.sha256(
        environment_path.read_bytes() + baseline_path.read_bytes()
    ).hexdigest()
    pipeline = ContentPipeline(
        data_root=data_root,
        adapter_version=f"{environment.client_generation}:pipeline-v1",
        input_fingerprint=fingerprint,
    )
    return pipeline, environment, baseline


def _pipeline_inputs(
    arguments: argparse.Namespace,
) -> tuple[ContentPipeline, EnvironmentConfig, dict[str, Any]]:
    return _pipeline_inputs_for_environment(
        environment_path=_environment_path(arguments.environment),
        baseline_path=(
            REPO_ROOT / "catalog/baselines" / f"{arguments.environment}.json"
        ),
        data_root=_path(arguments.data_root),
    )


def _checkpoint_json(
    checkpoint: JobCheckpoint,
    *,
    invalidated: bool = False,
) -> dict[str, object]:
    gate = checkpoint.gate_reason
    return {
        "jobId": checkpoint.job_id,
        "environmentId": checkpoint.environment_id,
        "contentReleaseRef": checkpoint.content_release_ref,
        "status": checkpoint.status.value,
        "completedStages": list(checkpoint.completed_stages),
        "retryFromStage": None if gate is None else gate.retry_from_stage,
        "gateSummary": None if gate is None else gate.summary,
        "invalidated": invalidated,
    }


def _run_pipeline(arguments: argparse.Namespace) -> int:
    pipeline, environment, baseline = _pipeline_inputs(arguments)
    result = pipeline.run(
        job_id=arguments.job_id,
        environment_id=environment.environment_id,
        content_release_ref=baseline["identity"]["contentReleaseId"],
        adapter=_ConfiguredPipelineAdapter(environment_enabled=environment.enabled),
    )
    print(json.dumps(_checkpoint_json(result.checkpoint), sort_keys=True))
    return 2 if result.checkpoint.gate_reason is not None else 0


def _run_scheduled_environment(environment: EnvironmentConfig, *, environment_path: Path,
                               baseline_path: Path, data_root: Path) -> str:
    """Global network discovery is not bound to a verified adapter yet."""
    return JobStatus.UNSUPPORTED_PROTOCOL.value


def _run_all_enabled(arguments: argparse.Namespace) -> int:
    config_root = _path(arguments.config_root)
    baseline_root = _path(arguments.baseline_root)
    data_root = _path(arguments.data_root)
    EnvironmentRegistry.load(config_root)

    def run_environment(environment: EnvironmentConfig) -> str:
        return _run_scheduled_environment(
            environment,
            environment_path=config_root / f"{environment.environment_id}.toml",
            baseline_path=baseline_root / f"{environment.environment_id}.json",
            data_root=data_root,
        )

    report = EnvironmentScheduler(
        config_root=config_root,
        data_root=data_root,
    ).run(run_environment)
    print(
        json.dumps(
            {
                "results": [
                    {
                        "detail": item.detail,
                        "environmentId": item.environment_id,
                        "status": item.status,
                    }
                    for item in report.results
                ],
                "status": "partial_failure" if report.failed else "ok",
            },
            sort_keys=True,
        )
    )
    return 2 if report.failed else 0


def _run(arguments: argparse.Namespace) -> int:
    if arguments.all_enabled:
        if arguments.job_id is not None:
            raise ValueError("--job-id cannot be used with --all-enabled")
        return _run_all_enabled(arguments)
    if arguments.job_id is None:
        raise ValueError("--job-id is required with --environment")
    return _run_pipeline(arguments)


def _resume_pipeline(arguments: argparse.Namespace) -> int:
    pipeline, environment, _ = _pipeline_inputs(arguments)
    result = pipeline.resume(
        job_id=arguments.job_id,
        adapter=_ConfiguredPipelineAdapter(environment_enabled=environment.enabled),
    )
    print(
        json.dumps(
            _checkpoint_json(result.checkpoint, invalidated=result.invalidated),
            sort_keys=True,
        )
    )
    return 2 if result.checkpoint.gate_reason is not None else 0


def _pipeline_status(arguments: argparse.Namespace) -> int:
    pipeline = ContentPipeline(
        data_root=_path(arguments.data_root),
        adapter_version="status-reader",
        input_fingerprint="0" * 64,
    )
    print(json.dumps(_checkpoint_json(pipeline.status(arguments.job_id)), sort_keys=True))
    return 0


def _validate_release(arguments: argparse.Namespace) -> int:
    environment = load_environment_config(_environment_path(arguments.environment))
    platform = load_platform_config(
        REPO_ROOT / "config/resource-platform.toml",
        project_root=REPO_ROOT,
    )
    data_root = _path(arguments.data_root) if arguments.data_root else platform.data_root
    baseline_index_path = (
        REPO_ROOT / "catalog/baselines" / f"{arguments.environment}.json"
    )
    baseline_index = json.loads(baseline_index_path.read_text(encoding="utf-8"))
    baseline_id = baseline_index["identity"]["contentReleaseId"]
    release_id = arguments.release_id or baseline_id
    repository = ReleaseRepository(data_root)
    candidate = repository.load_manifest(
        environment.region,
        environment.channel,
        release_id,
    )
    baseline = repository.load_manifest(
        environment.region,
        environment.channel,
        baseline_id,
    )
    report = ContentValidator(
        object_store=FileObjectStore(data_root),
        max_critical_table_drop_ratio=platform.max_critical_table_drop_ratio,
    ).validate(candidate, baseline=baseline)
    print(
        json.dumps(
            {
                "contentReleaseId": release_id,
                "environmentId": environment.environment_id,
                "status": "valid" if report.valid else "validation_failed",
                "issues": [
                    {"code": issue.code, "message": issue.message, "path": issue.path}
                    for issue in report.issues
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.valid else 2


def _list_environments(arguments: argparse.Namespace) -> int:
    registry = EnvironmentRegistry.load(_path(arguments.config_root))
    print(
        json.dumps(
            {
                "environments": [
                    {
                        "adapter": environment.adapter,
                        "channel": environment.channel.value,
                        "clientBuildRef": environment.client_build_ref,
                        "enabled": environment.enabled,
                        "environmentId": environment.environment_id,
                        "gateReason": environment.gate_reason,
                        "region": environment.region.value,
                        "status": environment.activation_state,
                    }
                    for environment in registry.environments
                ]
            },
            sort_keys=True,
        )
    )
    return 0


def _replay_source(arguments: argparse.Namespace) -> int:
    config_root = _path(arguments.config_root)
    environment = EnvironmentRegistry.load(config_root).get(arguments.environment)
    fixture_path = _path(arguments.fixture)
    source = ReplaySourceAdapter.from_fixture(
        fixture_path,
        environment=environment,
    )
    fingerprint = hashlib.sha256(
        (config_root / f"{environment.environment_id}.toml").read_bytes()
        + fixture_path.read_bytes()
    ).hexdigest()
    pipeline = ContentPipeline(
        data_root=_path(arguments.data_root),
        adapter_version=f"{environment.client_generation}:source-replay-v1",
        input_fingerprint=fingerprint,
    )
    adapter = ReplayPipelineAdapter(source)
    try:
        pipeline.status(arguments.job_id)
    except PipelineError:
        result = pipeline.run(
            job_id=arguments.job_id,
            environment_id=environment.environment_id,
            content_release_ref=(
                f"{environment.environment_id}-"
                f"{source.version_vector.fingerprint()[:16]}"
            ),
            adapter=adapter,
        )
    else:
        result = pipeline.resume(job_id=arguments.job_id, adapter=adapter)
    report = _checkpoint_json(result.checkpoint, invalidated=result.invalidated)
    report["sourceStatus"] = source.source_status
    print(json.dumps(report, sort_keys=True))
    return 0 if result.checkpoint.status == JobStatus.READY_FOR_PUBLISH else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ournotes-resource-pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_set = subparsers.add_parser("inspect-package-set", help="inspect a complete local APK split set")
    inspect_set.add_argument("--apk-root", required=True)
    inspect_set.add_argument("--region", choices=[value.value for value in Region], required=True)
    inspect_set.add_argument("--channel", choices=[value.value for value in Channel], required=True)
    inspect_set.add_argument("--output", required=True)
    inspect_set.set_defaults(handler=_inspect_package_set)

    profile = subparsers.add_parser("build-client-profile", help="build a secret-safe structural client profile")
    profile.add_argument("--package-set", required=True)
    profile.add_argument("--methods", required=True)
    profile.add_argument("--analysis-summary", required=True)
    profile.add_argument("--metadata-version", type=int, required=True)
    profile.add_argument("--abi", required=True)
    profile.add_argument("--private-output", required=True)
    profile.add_argument("--public-output", required=True)
    profile.set_defaults(handler=_build_client_profile)

    aggregate = subparsers.add_parser("aggregate-asset-manifests", help="aggregate exported bundle manifests")
    aggregate.add_argument("--bundle-root", required=True)
    aggregate.add_argument("--catalog", required=True)
    aggregate.add_argument("--output", required=True)
    aggregate.set_defaults(handler=_aggregate_assets)

    register = subparsers.add_parser(
        "register-golden",
        help="archive and register a confirmed Golden release",
    )
    register.add_argument(
        "--region",
        choices=[value.value for value in Region],
        required=True,
    )
    register.add_argument(
        "--channel",
        choices=[value.value for value in Channel],
        required=True,
    )
    register.add_argument("--apk", required=True)
    register.add_argument("--package-set-manifest")
    register.add_argument("--client-profile")
    register.add_argument("--private-manifest-output")
    register.add_argument("--il2cpp", required=True)
    register.add_argument("--metadata", required=True)
    register.add_argument("--metadata-version", type=int, required=True)
    register.add_argument("--catalog", required=True)
    register.add_argument("--catalog-hash", required=True)
    register.add_argument("--master-version", required=True)
    register.add_argument("--master-root", required=True)
    register.add_argument("--asset-manifest", required=True)
    register.add_argument("--auth-profile-ref", required=True)
    register.add_argument("--data-root", default="data")
    register.add_argument(
        "--baseline",
        required=True,
    )
    register.set_defaults(handler=_register)

    verify = subparsers.add_parser(
        "verify-golden",
        help="verify a Golden release using only archived local objects",
    )
    verify.add_argument("--data-root", default="data")
    verify.add_argument(
        "--baseline",
        required=True,
    )
    verify.add_argument("--private-manifest-output")
    verify.set_defaults(handler=_verify)

    probe = subparsers.add_parser(
        "probe",
        help="probe one configured content environment",
    )
    probe.add_argument("--environment", required=True)
    probe.set_defaults(handler=_probe)

    run = subparsers.add_parser("run", help="start recoverable content pipeline jobs")
    run_scope = run.add_mutually_exclusive_group(required=True)
    run_scope.add_argument("--environment")
    run_scope.add_argument("--all-enabled", action="store_true")
    run.add_argument("--job-id")
    run.add_argument("--data-root", default="data")
    run.add_argument("--config-root", default="config/environments")
    run.add_argument("--baseline-root", default="catalog/baselines")
    run.set_defaults(handler=_run)

    resume = subparsers.add_parser("resume", help="resume a recoverable pipeline job")
    resume.add_argument("--environment", required=True)
    resume.add_argument("--job-id", required=True)
    resume.add_argument("--data-root", default="data")
    resume.set_defaults(handler=_resume_pipeline)

    status = subparsers.add_parser("status", help="show a pipeline checkpoint")
    status.add_argument("--job-id", required=True)
    status.add_argument("--data-root", default="data")
    status.set_defaults(handler=_pipeline_status)

    validate = subparsers.add_parser("validate", help="validate a candidate release")
    validate.add_argument("--environment", required=True)
    validate.add_argument("--release-id")
    validate.add_argument("--data-root")
    validate.set_defaults(handler=_validate_release)

    environments = subparsers.add_parser(
        "environments",
        help="list isolated resource synchronization environments",
    )
    environments.add_argument("--config-root", default="config/environments")
    environments.set_defaults(handler=_list_environments)

    replay = subparsers.add_parser(
        "replay-source",
        help="replay sanitized source evidence through the recoverable pipeline",
    )
    replay.add_argument("--environment", required=True)
    replay.add_argument("--fixture", required=True)
    replay.add_argument("--job-id", required=True)
    replay.add_argument("--data-root", default="data")
    replay.add_argument("--config-root", default="config/environments")
    replay.set_defaults(handler=_replay_source)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
