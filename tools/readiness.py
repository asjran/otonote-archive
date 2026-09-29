#!/usr/bin/env python3
"""Build the machine-readable 8/6 international-test readiness report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


CATALOG_REPORT = Path("catalog/site-data/build-report.json")
EVIDENCE_FILES = {
    "globalIntake": Path("output/readiness/global-intake.json"),
    "packageDiff": Path("output/readiness/package-diff.json"),
    "databaseShards": Path("output/readiness/database-shards.json"),
    "mediaIndex": Path("output/readiness/media-index.json"),
    "monitor": Path("output/readiness/monitor.json"),
    "shadowRehearsal": Path("output/readiness/shadow-rehearsal.json"),
    "ci": Path("output/readiness/ci.json"),
    "browserRegression": Path("output/readiness/browser-regression.json"),
    "productionPerformance": Path("output/readiness/production-performance.json"),
}


def _read_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evidence_status(value: Mapping[str, Any] | None) -> bool:
    return value is not None and value.get("status") == "passed"


def _is_sha256(value: object, *, prefixed: bool = False) -> bool:
    text = str(value or "")
    if prefixed:
        if not text.startswith("sha256:"):
            return False
        text = text.removeprefix("sha256:")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _task(status: str, reasons: list[str], evidence: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "reasons": reasons,
        "evidence": evidence,
    }


def build_readiness_report(
    root: Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 48,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Aggregate current checklist evidence without claiming external work."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    catalog_path = root / CATALOG_REPORT
    catalog = _read_json(catalog_path)
    generated_at = _parse_timestamp(None if catalog is None else catalog.get("generatedAt"))
    age_hours = None
    if generated_at is not None:
        age_hours = max(0.0, (now - generated_at).total_seconds() / 3600)
    catalog_fresh = catalog is not None and age_hours is not None and age_hours <= max_age_hours

    warnings = list(catalog.get("warnings", [])) if catalog else []
    full_combo_warnings = [
        warning
        for warning in warnings
        if isinstance(warning, str)
        and "differs from official Full Combo" in warning
    ]
    validation_errors = list(catalog.get("validationErrors", [])) if catalog else []
    metrics = {
        "musicChartCount": None if catalog is None else catalog.get("musicChartCount"),
        "warningCount": len(warnings),
        "fullComboMismatchCount": len(full_combo_warnings),
        "pendingAssetCount": None if catalog is None else catalog.get("pendingAssetCount"),
        "missingSkillIconCount": None if catalog is None else catalog.get("missingSkillIconCount"),
        "unexplainedPendingAssetCount": None if catalog is None else catalog.get("unexplainedPendingAssetCount"),
        "unexplainedMissingSkillIconCount": None if catalog is None else catalog.get("unexplainedMissingSkillIconCount"),
        "catalogValidationErrorCount": len(validation_errors),
    }

    evidence = {
        name: _read_json(root / relative)
        for name, relative in EVIDENCE_FILES.items()
    }

    global_input_present = (root / "input/global/apks").is_dir()
    global_intake = evidence["globalIntake"]
    global_intake_passed = (
        _evidence_status(global_intake)
        and global_intake.get("sourceStatus") == "offline_package"
        and global_intake.get("remoteValidation") == "external_gate"
        and global_intake.get("remoteValidated") is False
        and global_intake.get("activationAttempted") is False
        and global_intake.get("autoPublish") is False
        and set(global_intake.get("projections", {})) == {"zh-CN", "zh-TW", "en", "ja"}
    ) if global_intake else False

    tasks: dict[str, dict[str, Any]] = {}
    tasks["T1"] = _task(
        "passed" if _evidence_status(evidence["packageDiff"]) else "failed",
        [] if _evidence_status(evidence["packageDiff"]) else ["package_diff_missing_or_failed"],
        [str(EVIDENCE_FILES["packageDiff"])],
    )

    t2_reasons: list[str] = []
    if not catalog_fresh:
        t2_reasons.append("stale" if catalog is not None else "catalog_report_missing")
    if full_combo_warnings:
        t2_reasons.append(f"full_combo_mismatches:{len(full_combo_warnings)}")
    if validation_errors:
        t2_reasons.append(f"catalog_validation_errors:{len(validation_errors)}")
    tasks["T2"] = _task(
        "passed" if not t2_reasons else "failed",
        t2_reasons,
        [str(CATALOG_REPORT)],
    )

    pending_assets = metrics["unexplainedPendingAssetCount"]
    missing_icons = metrics["unexplainedMissingSkillIconCount"]
    t3_reasons: list[str] = []
    if not catalog_fresh:
        t3_reasons.append("stale" if catalog is not None else "catalog_report_missing")
    if pending_assets not in (0, None):
        t3_reasons.append(f"pending_assets:{pending_assets}")
    if missing_icons not in (0, None):
        t3_reasons.append(f"missing_skill_icons:{missing_icons}")
    if pending_assets is None:
        t3_reasons.append("pending_asset_metric_missing")
    if missing_icons is None:
        t3_reasons.append("missing_skill_icon_metric_missing")
    tasks["T3"] = _task(
        "passed" if not t3_reasons else "failed",
        t3_reasons,
        [str(CATALOG_REPORT)],
    )

    shards_passed = _evidence_status(evidence["databaseShards"])
    media_passed = _evidence_status(evidence["mediaIndex"])
    tasks["A1"] = _task(
        "passed" if shards_passed else "failed",
        [] if shards_passed else ["database_shard_evidence_missing_or_failed"],
        [str(EVIDENCE_FILES["databaseShards"])],
    )
    tasks["A2"] = _task(
        "passed" if media_passed else "failed",
        [] if media_passed else ["media_index_evidence_missing_or_failed"],
        [str(EVIDENCE_FILES["mediaIndex"])],
    )
    tasks["T4"] = _task(
        "passed" if shards_passed and media_passed else "failed",
        []
        if shards_passed and media_passed
        else ["database_or_media_performance_gate_failed"],
        [str(EVIDENCE_FILES["databaseShards"]), str(EVIDENCE_FILES["mediaIndex"])],
    )

    monitor_passed = _evidence_status(evidence["monitor"])
    rehearsal_passed = _evidence_status(evidence["shadowRehearsal"])
    tasks["A3"] = _task(
        "passed" if monitor_passed else "failed",
        [] if monitor_passed else ["monitor_evidence_missing_or_failed"],
        [str(EVIDENCE_FILES["monitor"])],
    )
    tasks["A4"] = _task(
        "passed" if rehearsal_passed else "failed",
        [] if rehearsal_passed else ["shadow_rehearsal_evidence_missing_or_failed"],
        [str(EVIDENCE_FILES["shadowRehearsal"])],
    )

    ci_payload = evidence["ci"]
    browser_payload = evidence["browserRegression"]
    ci_generated_at = _parse_timestamp(
        None if ci_payload is None else ci_payload.get("generatedAt")
    )
    browser_generated_at = _parse_timestamp(
        None if browser_payload is None else browser_payload.get("generatedAt")
    )
    ci_fresh = (
        ci_generated_at is not None
        and max(0.0, (now - ci_generated_at).total_seconds() / 3600)
        <= max_age_hours
    )
    browser_fresh = (
        browser_generated_at is not None
        and max(0.0, (now - browser_generated_at).total_seconds() / 3600)
        <= max_age_hours
    )
    ci_passed = _evidence_status(ci_payload) and ci_fresh
    ci_revision_matches = (
        expected_revision is None
        or (
            ci_payload is not None
            and ci_payload.get("revision") == expected_revision
        )
    )
    ci_passed = ci_passed and ci_revision_matches
    browser_passed = (
        _evidence_status(browser_payload)
        and browser_fresh
        and ci_payload is not None
        and browser_payload.get("gitHead") == ci_payload.get("revision")
    )
    tasks["T5"] = _task(
        "passed" if ci_passed and browser_passed else "failed",
        [] if ci_passed and browser_passed else ["ci_or_browser_regression_gate_failed"],
        [str(EVIDENCE_FILES["ci"]), str(EVIDENCE_FILES["browserRegression"])],
    )
    site_performance = (
        ci_payload.get("sitePerformance")
        if isinstance(ci_payload, dict)
        else None
    )
    local_performance_passed = (
        ci_passed
        and ci_payload is not None
        and ci_payload.get("mode") == "local-runtime"
        and isinstance(site_performance, dict)
        and site_performance.get("status") == "passed"
        and site_performance.get("head") == ci_payload.get("revision")
        and isinstance(site_performance.get("contract"), dict)
        and _is_sha256(site_performance["contract"].get("digest"), prefixed=True)
        and isinstance(site_performance.get("baseline"), dict)
        and _is_sha256(site_performance["baseline"].get("sha256"))
        and isinstance(site_performance.get("browser"), dict)
        and _is_sha256(site_performance["browser"].get("sha256"))
        and isinstance(site_performance.get("loadCurve"), dict)
        and _is_sha256(site_performance["loadCurve"].get("sha256"))
    )
    production_performance = evidence["productionPerformance"]
    production_generated_at = _parse_timestamp(
        None
        if production_performance is None
        else production_performance.get("generatedAt")
    )
    production_fresh = (
        production_generated_at is not None
        and max(0.0, (now - production_generated_at).total_seconds() / 3600)
        <= max_age_hours
    )
    if not local_performance_passed:
        tasks["O1"] = _task(
            "failed",
            ["o1_local_performance_evidence_missing_or_failed"],
            [str(EVIDENCE_FILES["ci"])],
        )
    elif production_performance is None or production_performance.get("status") == "external_gate":
        production_reasons = (
            list(production_performance.get("reasonCodes", []))
            if production_performance is not None
            else ["production_performance_evidence_missing"]
        )
        tasks["O1"] = _task(
            "external_gate",
            production_reasons,
            [
                str(EVIDENCE_FILES["ci"]),
                str(EVIDENCE_FILES["productionPerformance"]),
            ],
        )
    elif not production_fresh:
        tasks["O1"] = _task(
            "external_gate",
            ["production_performance_evidence_stale_or_unversioned"],
            [
                str(EVIDENCE_FILES["ci"]),
                str(EVIDENCE_FILES["productionPerformance"]),
            ],
        )
    elif production_performance.get("status") == "passed":
        tasks["O1"] = _task(
            "passed",
            [],
            [
                str(EVIDENCE_FILES["ci"]),
                str(EVIDENCE_FILES["productionPerformance"]),
            ],
        )
    else:
        tasks["O1"] = _task(
            "failed",
            ["production_performance_evidence_invalid_or_failed"],
            [str(EVIDENCE_FILES["productionPerformance"])],
        )
    if not global_input_present:
        tasks["E0"] = _task(
            "external_gate", ["global_package_input_missing"],
            [str(EVIDENCE_FILES["globalIntake"])],
        )
    elif global_intake_passed:
        tasks["E0"] = _task(
            "passed", [], [str(EVIDENCE_FILES["globalIntake"])],
        )
    else:
        tasks["E0"] = _task(
            "failed", ["global_offline_intake_incomplete"],
            [str(EVIDENCE_FILES["globalIntake"])],
        )
    tasks["B"] = _task(
        "external_gate",
        ["global_remote_protocol_unverified"],
        ["authorized login and stable remote probes"],
    )
    tasks["C"] = _task(
        "excluded",
        ["explicitly_out_of_scope"],
        ["approved scope boundary"],
    )

    current_scope = ("T1", "T2", "T3", "T4", "T5", "A1", "A2", "A3", "A4", "O1")
    failed = [name for name in current_scope if tasks[name]["status"] == "failed"]
    if tasks["E0"]["status"] == "failed":
        failed.append("E0")
    external_gates = ["B"]
    if tasks["O1"]["status"] == "external_gate":
        external_gates.append("O1")
    summary_status = "failed" if failed else "external_gate"
    return {
        "schemaVersion": 1,
        "generatedAt": now.isoformat(),
        "scope": {
            "current": list(current_scope),
            "offlineIntake": ["E0"],
            "external": ["B"],
            "excluded": ["C"],
        },
        "inputs": {
            "catalogBuildReport": {
                "path": str(CATALOG_REPORT),
                "present": catalog is not None,
                "generatedAt": None if generated_at is None else generated_at.isoformat(),
                "ageHours": None if age_hours is None else round(age_hours, 2),
                "fresh": catalog_fresh,
            },
            "evidence": {
                name: {
                    "path": str(path),
                    "present": evidence[name] is not None,
                    "status": None if evidence[name] is None else evidence[name].get("status"),
                }
                for name, path in EVIDENCE_FILES.items()
            },
        },
        "metrics": metrics,
        "tasks": tasks,
        "summary": {
            "status": summary_status,
            "failedCurrentTasks": failed,
            "externalGates": external_gates,
            "excludedTasks": ["C"],
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# OurNotes 8/6 国际服测试准备度",
        "",
        f"总体状态：`{report['summary']['status']}`",
        "",
        "## 当前指标",
        "",
        f"- 正式谱面：{metrics['musicChartCount']}",
        f"- 构建警告总数：{metrics['warningCount']}",
        f"- Full Combo 不匹配：{metrics['fullComboMismatchCount']}",
        f"- pendingAsset：{metrics['pendingAssetCount']}",
        f"- 缺失技能图标：{metrics['missingSkillIconCount']}",
        f"- 未解释资源缺口：{metrics['unexplainedPendingAssetCount']}",
        f"- 未解释技能图标缺口：{metrics['unexplainedMissingSkillIconCount']}",
        "",
        "## 清单状态",
        "",
        "| 任务 | 状态 | 原因 |",
        "| --- | --- | --- |",
    ]
    for name, task in report["tasks"].items():
        reasons = ", ".join(task["reasons"]) or "-"
        lines.append(f"| {name} | `{task['status']}` | {reasons} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="output/readiness/readiness.json")
    parser.add_argument("--markdown", default="output/readiness/readiness.md")
    parser.add_argument("--max-age-hours", type=int, default=48)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    expected_revision = (
        completed.stdout.strip() if completed.returncode == 0 else None
    )
    report = build_readiness_report(
        root,
        max_age_hours=args.max_age_hours,
        expected_revision=expected_revision,
    )
    output = root / args.output
    markdown = root / args.markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["summary"]["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
