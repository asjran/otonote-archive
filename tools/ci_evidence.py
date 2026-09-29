#!/usr/bin/env python3
"""Record a successful complete CI run for the readiness aggregator."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.artifact_registry import schema_versions  # noqa: E402
from tools.performance_contract import load_performance_contract  # noqa: E402
from tools.site_artifact import verify_artifact  # noqa: E402


def current_revision(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def build_identity(
    root: Path,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    release_index_path = (
        root / "site/src/data/generated/release-index.json"
    )
    package_lock_path = root / "site/package-lock.json"
    release_index_bytes = release_index_path.read_bytes()
    release_index = json.loads(release_index_bytes)
    references = {
        (
            str(item["region"]),
            str(item["channel"]),
            str(item["contentReleaseId"]),
        )
        for item in release_index["projections"]
    }
    identity: dict[str, object] = {
        "contentReleases": [
            {"region": region, "channel": channel, "id": release_id}
            for region, channel, release_id in sorted(references)
        ],
        "releaseIndexSha256": hashlib.sha256(
            release_index_bytes
        ).hexdigest(),
        "packageLockSha256": hashlib.sha256(
            package_lock_path.read_bytes()
        ).hexdigest(),
        "schemaVersions": schema_versions(),
    }
    if artifact_root is not None:
        revision = current_revision(root)
        artifact = verify_artifact(
            artifact_root,
            expected_git_commit=revision,
            package_lock=package_lock_path,
            release_index=release_index_path,
        )
        if artifact["contentReleases"] != identity["contentReleases"]:
            raise ValueError("Site Artifact ContentRelease identity is stale")
        identity.update(
            {
                "siteReleaseId": artifact["siteReleaseId"],
                "artifactManifestSha256": artifact[
                    "artifactManifestSha256"
                ],
                "packageLockSha256": artifact["packageLockSha256"],
                "schemaVersions": artifact["schemas"],
            }
        )
    return identity


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _canonical_json_digest(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("performance evidence timestamp is missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("performance evidence timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def build_site_performance_evidence(
    *,
    root: Path,
    revision: str,
    contract_path: Path,
    baseline_path: Path,
    browser_report_path: Path,
    load_curve_report_path: Path,
    not_before: datetime,
) -> dict[str, object]:
    """Validate and bind one local browser/load run to its immutable inputs."""
    contract_payload = _read_json_object(contract_path)
    contract = load_performance_contract(contract_path)
    contract_digest = _canonical_json_digest(contract_payload)
    expected_case_ids = [case.id for case in contract.browser_cases]

    baseline = _read_json_object(baseline_path)
    if int(baseline.get("schemaVersion", 0)) != 1:
        raise ValueError("performance baseline schema mismatch")
    if baseline.get("contractDigest") != contract_digest:
        raise ValueError("performance baseline contract digest mismatch")
    runner = str(baseline.get("runner") or "")
    if not runner or runner == "unfixed":
        raise ValueError("performance baseline runner is not fixed")
    baseline_cases = baseline.get("cases")
    if not isinstance(baseline_cases, list):
        raise ValueError("performance baseline cases are missing")
    baseline_case_ids = [
        str(item.get("id"))
        for item in baseline_cases
        if isinstance(item, dict)
    ]
    if len(baseline_case_ids) != len(expected_case_ids) or baseline_case_ids != expected_case_ids:
        raise ValueError("performance baseline case matrix mismatch")

    browser = _read_json_object(browser_report_path)
    if int(browser.get("schemaVersion", 0)) != 2:
        raise ValueError("browser performance report schema mismatch")
    if browser.get("gitHead") != revision:
        raise ValueError("browser performance report HEAD mismatch")
    if browser.get("contractDigest") != contract_digest:
        raise ValueError("browser performance report contract digest mismatch")
    if browser.get("runner") != runner:
        raise ValueError("browser performance report runner mismatch")
    if browser.get("budgetOnly") is not True or browser.get("writeBaseline") is not False:
        raise ValueError("browser performance report mode mismatch")
    baseline_reference = Path(str(browser.get("baseline") or ""))
    if not baseline_reference.is_absolute():
        baseline_reference = root / baseline_reference
    if baseline_reference.resolve() != baseline_path.resolve():
        raise ValueError("browser performance report baseline path mismatch")
    browser_results = browser.get("results")
    if not isinstance(browser_results, list):
        raise ValueError("browser performance results are missing")
    browser_case_ids = [
        str(item.get("id"))
        for item in browser_results
        if isinstance(item, dict)
    ]
    if len(browser_case_ids) != len(expected_case_ids) or browser_case_ids != expected_case_ids:
        raise ValueError("browser performance case matrix mismatch")
    if any(item.get("pass") is not True for item in browser_results if isinstance(item, dict)):
        raise ValueError("browser performance hard gate failed")
    if _parse_timestamp(browser.get("generatedAt")) < not_before:
        raise ValueError("browser performance report is stale")

    curve = _read_json_object(load_curve_report_path)
    if int(curve.get("schemaVersion", 0)) != 1:
        raise ValueError("load curve report schema mismatch")
    if curve.get("gitHead") != revision:
        raise ValueError("load curve report HEAD mismatch")
    if curve.get("contractDigest") != contract_digest:
        raise ValueError("load curve report contract digest mismatch")
    if curve.get("pass") is not True:
        raise ValueError("load curve hard gate failed")
    if str(curve.get("server") or "") in {"", "unspecified"}:
        raise ValueError("load curve server implementation is missing")
    if int(curve.get("warmupRequests", -1)) != contract.warmup_requests:
        raise ValueError("load curve warmup mismatch")
    route_summary = curve.get("routeSummary")
    if not isinstance(route_summary, dict) or (
        route_summary.get("method") != "GET"
        or route_summary.get("count") != len(contract.load_paths)
        or route_summary.get("paths") != list(contract.load_paths)
    ):
        raise ValueError("load curve route summary mismatch")
    stages = curve.get("stages")
    if not isinstance(stages, list):
        raise ValueError("load curve stages are missing")
    actual_stages = [
        (
            item.get("concurrency"),
            item.get("requests"),
            item.get("hardGate"),
            item.get("gate"),
        )
        for item in stages
        if isinstance(item, dict)
    ]
    expected_stage_shape = [
        (5, 100, True),
        (10, 200, True),
        (20, 200, False),
        (50, 100, False),
    ]
    if (
        len(actual_stages) != 4
        or [item[:3] for item in actual_stages] != expected_stage_shape
        or [item[3] for item in actual_stages[:2]]
        != ["hard_passed", "hard_passed"]
    ):
        raise ValueError("load curve stage contract mismatch")
    observational_gates = {"observed", "observed_with_errors"}
    if any(item[3] not in observational_gates for item in actual_stages[2:]):
        raise ValueError("load curve observational stage mismatch")
    if _parse_timestamp(curve.get("startedAt")) < not_before:
        raise ValueError("load curve report is stale")

    return {
        "status": "passed",
        "head": revision,
        "contract": {
            "path": str(contract_path),
            "digest": contract_digest,
            "browserCaseCount": len(expected_case_ids),
            "loadPathCount": len(contract.load_paths),
        },
        "baseline": {
            "path": str(baseline_path),
            "sha256": _file_sha256(baseline_path),
            "runner": runner,
            "gitHead": baseline.get("gitHead"),
        },
        "browser": {
            "path": str(browser_report_path),
            "sha256": _file_sha256(browser_report_path),
            "caseCount": len(browser_case_ids),
        },
        "loadCurve": {
            "path": str(load_curve_report_path),
            "sha256": _file_sha256(load_curve_report_path),
            "stageConcurrencies": [item[0] for item in actual_stages],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=Path("output/readiness/ci.json"))
    parser.add_argument(
        "--mode",
        choices=("worker-container", "local-runtime"),
        required=True,
    )
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--performance-contract", type=Path)
    parser.add_argument("--performance-baseline", type=Path)
    parser.add_argument("--browser-performance-report", type=Path)
    parser.add_argument("--load-curve-report", type=Path)
    parser.add_argument("--performance-not-before")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        output.unlink(missing_ok=True)
        if args.mode == "local-runtime" and args.artifact_root is None:
            parser.error("--artifact-root is required for local-runtime evidence")
        performance_values = (
            args.performance_contract,
            args.performance_baseline,
            args.browser_performance_report,
            args.load_curve_report,
            args.performance_not_before,
        )
        performance_input_count = sum(value is not None for value in performance_values)
        if (
            args.mode == "local-runtime"
            and performance_input_count not in {0, len(performance_values)}
        ):
            parser.error("performance evidence must be provided as a complete set")
        if args.mode == "worker-container" and performance_input_count:
            parser.error("site performance evidence is not valid for worker-container")
        revision = current_revision(root)
        if not revision:
            raise ValueError("cannot resolve current Git HEAD")
        identity = build_identity(root, args.artifact_root)
        site_performance = (
            build_site_performance_evidence(
                root=root,
                revision=revision,
                contract_path=args.performance_contract.resolve(),
                baseline_path=args.performance_baseline.resolve(),
                browser_report_path=args.browser_performance_report.resolve(),
                load_curve_report_path=args.load_curve_report.resolve(),
                not_before=_parse_timestamp(args.performance_not_before),
            )
            if args.mode == "local-runtime" and performance_input_count
            else None
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(f"cannot record CI build identity: {exc}")
    common_checks = [
        "docs-status",
        "artifact-schema-registry",
        "python-unittest-discovery",
    ]
    checks = (
        [
            *common_checks,
            "node-test",
            "astro-check",
            "site-matrix-build",
            "site-artifact-verify",
            "build-performance-budget",
            *(["site-performance-gate"] if site_performance is not None else []),
        ]
        if args.mode == "local-runtime"
        else [
            *common_checks,
            "worker-runtime",
            "resource-pipeline-smoke",
        ]
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "mode": args.mode,
        "revision": revision,
        **identity,
        "checks": checks,
        "command": "tools/ci_verify.sh",
    }
    if site_performance is not None:
        payload["sitePerformance"] = site_performance
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "passed", "evidence": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
