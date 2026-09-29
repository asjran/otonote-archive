#!/usr/bin/env python3
"""Validate and summarize versioned scoring Golden Replays."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
STATUSES = {"fixture", "observed", "reconciled", "rejected"}


def validate_replay(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("unsupported_schema")
    for key in ("sampleId", "sourceReleaseId", "ruleSetVersion"):
        if not isinstance(value.get(key), str) or not value[key]:
            errors.append(f"required_string:{key}")
    status = value.get("verificationStatus")
    if status not in STATUSES:
        errors.append("invalid_verification_status")
    evidence = value.get("sourceEvidence")
    if not isinstance(evidence, list):
        errors.append("source_evidence_required")
    elif status in {"observed", "reconciled"} and not evidence:
        errors.append("client_evidence_required")
    for key in ("judgements", "scoreCommands"):
        if not isinstance(value.get(key), list):
            errors.append(f"required_array:{key}")
    formation = value.get("formation")
    if (
        not isinstance(formation, dict)
        or not isinstance(formation.get("totalPower"), int)
        or formation["totalPower"] < 0
    ):
        errors.append("invalid_total_power")
    chart = value.get("chart")
    events = chart.get("events") if isinstance(chart, dict) else None
    if not isinstance(events, list) or not events:
        errors.append("events_required")
    else:
        for index, event in enumerate(events):
            for key in (
                "notePercent",
                "judgementPercent",
                "comboPercent",
                "scorePercent",
                "fixedScore",
            ):
                if (
                    not isinstance(event, dict)
                    or not isinstance(event.get(key), int)
                    or isinstance(event.get(key), bool)
                ):
                    errors.append(f"integer_required:chart.events[{index}].{key}")
    expected = value.get("expected")
    if (
        not isinstance(expected, dict)
        or not isinstance(expected.get("finalScore"), int)
    ):
        errors.append("expected_score_required")
    return errors


def load_replays(root: Path) -> list[dict[str, Any]]:
    replays: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Golden Replay root must be an object: {path}")
        errors = validate_replay(value)
        if errors:
            raise ValueError(f"Invalid Golden Replay {path}: {', '.join(errors)}")
        replays.append({**value, "_path": path.as_posix()})
    return replays


def summarize_replays(replays: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(replay["verificationStatus"]) for replay in replays)
    releases = sorted({str(replay["sourceReleaseId"]) for replay in replays})
    reconciled = counts["reconciled"]
    return {
        "schemaVersion": 1,
        "status": "passed",
        "sampleCount": len(replays),
        "statusCounts": {
            status: counts[status]
            for status in ("fixture", "observed", "reconciled", "rejected")
        },
        "sourceReleaseIds": releases,
        "formalCapability": "reconciled" if reconciled else "external_gate",
        "gate": None if reconciled else "client_replay_sample_missing",
        "samples": [
            {
                "sampleId": replay["sampleId"],
                "sourceReleaseId": replay["sourceReleaseId"],
                "ruleSetVersion": replay["ruleSetVersion"],
                "verificationStatus": replay["verificationStatus"],
                "path": replay.get("_path"),
            }
            for replay in replays
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("catalog/baselines/scoring"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/readiness/scoring-replays.json"),
    )
    args = parser.parse_args()
    report = summarize_replays(load_replays(args.root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
