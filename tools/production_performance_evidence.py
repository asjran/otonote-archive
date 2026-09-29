#!/usr/bin/env python3
"""Evaluate exported production performance evidence without remote access."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


UTC = dt.timezone.utc
MONITOR_SCHEMA_VERSION = 3
DEPLOYMENT_SCHEMA_VERSION = 2
MIN_COMPLETE_NATURAL_DAYS = 7
MIN_REAL_SUCCESSFUL_DEPLOYMENTS = 5
MAX_HEARTBEAT_AGE = dt.timedelta(minutes=30)
MAX_COLLECTION_GAP = dt.timedelta(minutes=60)
RELEASE_WINDOW = dt.timedelta(minutes=30)
MAX_RELEASE_P95_RATIO = 2.0
MAX_RELEASE_P95_DELTA_MS = 250
MAX_MEDIA_P95_RATIO = 2.0
MAX_MEDIA_P95_DELTA_MS = 500
MAX_MEDIA_RECOVERY_RATIO = 1.5
MAX_MEDIA_RECOVERY_DELTA_MS = 250
PLACEHOLDER_RELEASE_IDS = {"", "unknown", "fixture", "local", "none", "null", "placeholder"}


def _parse_time(value: object) -> dt.datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value}")
    return parsed.astimezone(UTC)


def stabilize_reason_codes(reason_codes: Iterable[str]) -> list[str]:
    """Preserve first-seen diagnostic order while removing duplicates."""
    return list(dict.fromkeys(reason_codes))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _monitor_foundation(path: Path, as_of: dt.datetime) -> dict[str, object]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("monitor SQLite integrity check failed")
        meta = dict(db.execute("SELECT key, value FROM meta"))
        if int(meta.get("schema_version", 0)) != MONITOR_SCHEMA_VERSION:
            raise ValueError("unsupported monitor schema")
        heartbeat = _parse_time(meta.get("last_success"))
        buckets = [
            _parse_time(row[0])
            for row in db.execute(
                "SELECT DISTINCT bucket FROM minute_metrics ORDER BY bucket"
            )
        ]
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"invalid monitor SQLite: {exc}") from exc
    finally:
        db.close()

    buckets_by_day: dict[dt.date, list[dt.datetime]] = {}
    for bucket in buckets:
        if bucket.date() < as_of.date():
            buckets_by_day.setdefault(bucket.date(), []).append(bucket)
    complete_dates = set()
    for day, day_buckets in buckets_by_day.items():
        day_gaps = [
            later - earlier
            for earlier, later in zip(day_buckets, day_buckets[1:])
        ]
        if (
            day_buckets[0].time() <= dt.time(0, 30)
            and day_buckets[-1].time() >= dt.time(23, 30)
            and max(day_gaps, default=dt.timedelta(0)) <= MAX_COLLECTION_GAP
        ):
            complete_dates.add(day)
    ordered_complete_dates = sorted(complete_dates)
    longest_run = current_run = 0
    previous_day = None
    for day in ordered_complete_dates:
        current_run = (
            current_run + 1
            if previous_day is not None and day - previous_day == dt.timedelta(days=1)
            else 1
        )
        longest_run = max(longest_run, current_run)
        previous_day = day
    max_gap = max(
        (later - earlier for earlier, later in zip(buckets, buckets[1:])),
        default=dt.timedelta(0),
    )
    return {
        "completeNaturalDays": longest_run,
        "firstCompleteDay": min(complete_dates).isoformat() if complete_dates else None,
        "lastCompleteDay": max(complete_dates).isoformat() if complete_dates else None,
        "lastHeartbeat": heartbeat.isoformat(),
        "heartbeatAgeMinutes": round((as_of - heartbeat).total_seconds() / 60, 3),
        "heartbeatFresh": as_of - heartbeat <= MAX_HEARTBEAT_AGE,
        "maxGapMinutes": round(max_gap.total_seconds() / 60, 3),
        "hasCollectionGap": max_gap > MAX_COLLECTION_GAP,
    }


def _load_deployment_events(path: Path) -> list[dict[str, Any]]:
    events = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid deployment JSONL line {line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"invalid deployment JSONL object at line {line_number}")
        if int(event.get("schemaVersion", 0)) != DEPLOYMENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported deployment schema at line {line_number}")
        events.append(event)
    return events


def _has_positive_number(mapping: object, key: str) -> bool:
    if not isinstance(mapping, dict):
        return False
    try:
        return float(mapping.get(key, 0)) > 0
    except (TypeError, ValueError):
        return False


def _has_nonnegative_number(mapping: object, key: str) -> bool:
    if not isinstance(mapping, dict) or key not in mapping:
        return False
    try:
        return float(mapping[key]) >= 0
    except (TypeError, ValueError):
        return False


def _deployment_foundation(path: Path) -> dict[str, object]:
    events = _load_deployment_events(path)
    attempts: dict[str, dict[str, Any]] = {}
    for event in events:
        attempt_id = str(event.get("attemptId") or "")
        if not attempt_id:
            raise ValueError("deployment event missing attemptId")
        previous = attempts.get(attempt_id)
        if previous is None or _parse_time(event.get("finishedAt")) >= _parse_time(previous.get("finishedAt")):
            attempts[attempt_id] = event

    excluded: Counter[str] = Counter()
    real_successes = []
    for event in attempts.values():
        environment = str(event.get("environment") or "production").lower()
        release_id = str(event.get("releaseId") or "").strip()
        if str(event.get("command")) != "deploy":
            excluded["not_deploy"] += 1
        elif str(event.get("result")) != "success":
            excluded["not_success"] += 1
        elif environment in {"local", "fixture", "test", "testing"}:
            excluded["non_production"] += 1
        elif release_id.lower() in PLACEHOLDER_RELEASE_IDS or "fixture" in release_id.lower():
            excluded["placeholder_release"] += 1
        elif not _has_positive_number(event.get("disk"), "availableKiB"):
            excluded["missing_disk_evidence"] += 1
        elif not (
            _has_nonnegative_number(event.get("rsync"), "transferredFiles")
            and _has_nonnegative_number(event.get("rsync"), "transferredBytes")
        ):
            excluded["missing_transfer_evidence"] += 1
        else:
            real_successes.append(event)

    return {
        "eventCount": len(events),
        "uniqueAttemptCount": len(attempts),
        "realSuccessCount": len(real_successes),
        "excluded": dict(sorted(excluded.items())),
        "realSuccesses": real_successes,
    }


def evaluate_foundation_evidence(
    *,
    monitor_path: Path,
    deployment_path: Path,
    as_of: dt.datetime,
) -> dict[str, object]:
    monitor = _monitor_foundation(monitor_path, as_of.astimezone(UTC))
    deployments = _deployment_foundation(deployment_path)
    reason_codes = []
    if int(monitor["completeNaturalDays"]) < MIN_COMPLETE_NATURAL_DAYS:
        reason_codes.append("monitor_complete_days_insufficient")
    if not bool(monitor["heartbeatFresh"]):
        reason_codes.append("monitor_heartbeat_stale")
    if bool(monitor["hasCollectionGap"]):
        reason_codes.append("monitor_collection_gap")
    if int(deployments["realSuccessCount"]) < MIN_REAL_SUCCESSFUL_DEPLOYMENTS:
        reason_codes.append("deployment_real_successes_insufficient")
    return {
        "schemaVersion": 1,
        "status": "external_gate" if reason_codes else "passed",
        "reasonCodes": reason_codes,
        "monitor": monitor,
        "deployments": deployments,
    }


def _iso_minute(value: dt.datetime) -> str:
    return value.astimezone(UTC).replace(second=0, microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _percentile_from_histogram(histogram: dict[int, int], fraction: float) -> int:
    total = sum(histogram.values())
    if total <= 0:
        return 0
    target = max(1, int(total * fraction + 0.999999))
    running = 0
    for upper, count in sorted(
        histogram.items(), key=lambda item: 1_000_000_000 if item[0] == -1 else item[0]
    ):
        running += count
        if running >= target:
            return 10_000 if upper == -1 else upper
    return 0


def _release_window(
    db: sqlite3.Connection,
    start: dt.datetime,
    end: dt.datetime,
) -> dict[str, object]:
    since = _iso_minute(start)
    until = _iso_minute(end)
    category_bytes = {
        str(category): int(sent or 0)
        for category, sent in db.execute(
            """SELECT category, SUM(bytes) FROM minute_metrics
            WHERE bucket >= ? AND bucket < ?
              AND category NOT IN ('synthetic', 'health')
            GROUP BY category ORDER BY category""",
            (since, until),
        )
    }
    peak_row = db.execute(
        """SELECT MAX(bucket_bytes) FROM (
          SELECT bucket, SUM(bytes) AS bucket_bytes FROM minute_metrics
          WHERE bucket >= ? AND bucket < ?
            AND category NOT IN ('synthetic', 'health')
          GROUP BY bucket
        )""",
        (since, until),
    ).fetchone()
    histogram = {
        int(upper): int(requests or 0)
        for upper, requests in db.execute(
            """SELECT upper_ms, SUM(requests) FROM latency_histogram
            WHERE bucket >= ? AND bucket < ?
              AND category NOT IN ('synthetic', 'health', 'live2d', 'audio', 'video', 'download')
            GROUP BY upper_ms""",
            (since, until),
        )
    }
    server_5xx = db.execute(
        """SELECT COALESCE(SUM(requests), 0) FROM outcome_metrics
        WHERE bucket >= ? AND bucket < ?
          AND outcome IN ('server_error', 'server_error_unclassified')""",
        (since, until),
    ).fetchone()[0]
    capacity = db.execute(
        """SELECT COALESCE(SUM(requests), 0) FROM outcome_metrics
        WHERE bucket >= ? AND bucket < ? AND outcome = 'capacity_rejection'""",
        (since, until),
    ).fetchone()[0]
    total_requests = db.execute(
        """SELECT COALESCE(SUM(requests), 0) FROM minute_metrics
        WHERE bucket >= ? AND bucket < ?
          AND category NOT IN ('synthetic', 'health')""",
        (since, until),
    ).fetchone()[0]
    peak_bytes_per_minute = int((peak_row or [0])[0] or 0)
    return {
        "start": since,
        "end": until,
        "realRequests": int(total_requests or 0),
        "server5xx": int(server_5xx or 0),
        "capacityRejections": int(capacity or 0),
        "normalP95Ms": _percentile_from_histogram(histogram, 0.95),
        "categoryBytes": category_bytes,
        "peakMbps": round(peak_bytes_per_minute * 8 / 60 / 1_000_000, 9),
        "complete": bool(total_requests and histogram and category_bytes),
    }


def _release_windows(
    monitor_path: Path,
    releases: Iterable[dict[str, Any]],
) -> list[dict[str, object]]:
    try:
        db = sqlite3.connect(f"file:{monitor_path}?mode=ro", uri=True)
        windows = []
        for release in releases:
            deployed_at = _parse_time(release.get("finishedAt"))
            windows.append(
                {
                    "attemptId": release["attemptId"],
                    "releaseId": release["releaseId"],
                    "deployedAt": deployed_at.isoformat(),
                    "before": _release_window(
                        db, deployed_at - RELEASE_WINDOW, deployed_at
                    ),
                    "after": _release_window(
                        db, deployed_at, deployed_at + RELEASE_WINDOW
                    ),
                }
            )
        return windows
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"invalid monitor SQLite: {exc}") from exc
    finally:
        if "db" in locals():
            db.close()


def _load_json_document(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label} JSON object")
    if int(value.get("schemaVersion", 0)) != 1:
        raise ValueError(f"unsupported {label} schema")
    return value


def _load_curve_evidence(path: Path) -> tuple[dict[str, object], list[str]]:
    value = _load_json_document(path, "production load curve")
    reasons = []
    if value.get("scope") != "production" or value.get("controlled") is not True:
        reasons.append("production_load_curve_not_controlled")
    if value.get("routeSummary", {}).get("method") != "GET":
        reasons.append("production_load_curve_not_get_only")
    expected = [(5, 100), (10, 200), (20, 200), (50, 100)]
    stages = value.get("stages")
    actual = []
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, dict):
                actual.append((stage.get("concurrency"), stage.get("requests")))
    if actual != expected:
        reasons.append("production_load_curve_incomplete")
    elif any(int(stages[index].get("summary", {}).get("failures", -1)) != 0 for index in (0, 1)):
        reasons.append("production_load_curve_hard_gate_failed")
    return {
        "controlled": value.get("controlled") is True,
        "stageConcurrencies": [item[0] for item in actual],
        "stages": stages if isinstance(stages, list) else [],
    }, stabilize_reason_codes(reasons)


def _media_contention_evidence(path: Path) -> tuple[dict[str, object], list[str]]:
    value = _load_json_document(path, "media contention")
    reasons = []
    ordinary = value.get("ordinaryPages")
    media = value.get("media")
    required_p95 = ("p95BeforeMs", "p95DuringMs", "p95AfterMs")
    if (
        value.get("scope") != "production"
        or value.get("controlled") is not True
        or not isinstance(media, dict)
        or media.get("rangeRequest") is not True
    ):
        reasons.append("media_contention_not_controlled")
    if (
        not isinstance(ordinary, dict)
        or int(ordinary.get("requests", 0)) <= 0
        or any(float(ordinary.get(key, 0)) <= 0 for key in required_p95)
    ):
        reasons.append("media_contention_evidence_incomplete")
        ordinary = ordinary if isinstance(ordinary, dict) else {}
    if int(ordinary.get("errors", -1)) != 0:
        reasons.append("media_contention_ordinary_page_errors")
    before = float(ordinary.get("p95BeforeMs", 0) or 0)
    during = float(ordinary.get("p95DuringMs", 0) or 0)
    after = float(ordinary.get("p95AfterMs", 0) or 0)
    if before > 0 and during > max(
        before * MAX_MEDIA_P95_RATIO,
        before + MAX_MEDIA_P95_DELTA_MS,
    ):
        reasons.append("media_contention_p95_unbounded")
    if before > 0 and after > max(
        before * MAX_MEDIA_RECOVERY_RATIO,
        before + MAX_MEDIA_RECOVERY_DELTA_MS,
    ):
        reasons.append("media_contention_p95_not_recovered")
    return {
        "controlled": value.get("controlled") is True,
        "ordinaryPageRequests": int(ordinary.get("requests", 0)),
        "ordinaryPageErrors": int(ordinary.get("errors", -1)),
        "p95BeforeMs": ordinary.get("p95BeforeMs"),
        "p95DuringMs": ordinary.get("p95DuringMs"),
        "p95AfterMs": ordinary.get("p95AfterMs"),
    }, reasons


def evaluate_production_evidence(
    *,
    monitor_path: Path,
    deployment_path: Path,
    load_curve_path: Path,
    media_contention_path: Path,
    as_of: dt.datetime,
) -> dict[str, object]:
    report = evaluate_foundation_evidence(
        monitor_path=monitor_path,
        deployment_path=deployment_path,
        as_of=as_of,
    )
    release_windows = _release_windows(
        monitor_path,
        report["deployments"]["realSuccesses"],
    )
    reasons = list(report["reasonCodes"])
    if any(
        not bool(release[phase]["complete"])
        for release in release_windows
        for phase in ("before", "after")
    ):
        reasons.append("release_window_evidence_missing")
    if any(
        int(release[phase]["server5xx"]) > 0
        for release in release_windows
        for phase in ("before", "after")
    ):
        reasons.append("release_window_server_5xx")
    if any(
        int(release[phase]["capacityRejections"]) > 0
        for release in release_windows
        for phase in ("before", "after")
    ):
        reasons.append("release_window_capacity_rejection")
    if any(
        float(release["after"]["normalP95Ms"]) > max(
            float(release["before"]["normalP95Ms"]) * MAX_RELEASE_P95_RATIO,
            float(release["before"]["normalP95Ms"]) + MAX_RELEASE_P95_DELTA_MS,
        )
        for release in release_windows
        if release["before"]["complete"] and release["after"]["complete"]
    ):
        reasons.append("release_window_p95_regression")
    load_curve, curve_reasons = _load_curve_evidence(load_curve_path)
    media_contention, contention_reasons = _media_contention_evidence(
        media_contention_path
    )
    reasons.extend(curve_reasons)
    reasons.extend(contention_reasons)
    reasons = stabilize_reason_codes(reasons)
    report.update(
        {
            "generatedAt": as_of.astimezone(UTC).isoformat(),
            "asOf": as_of.astimezone(UTC).isoformat(),
            "inputs": {
                "monitorSha256": _file_sha256(monitor_path),
                "deploymentSha256": _file_sha256(deployment_path),
                "loadCurveSha256": _file_sha256(load_curve_path),
                "mediaContentionSha256": _file_sha256(media_contention_path),
            },
            "thresholds": {
                "releaseServer5xx": 0,
                "releaseCapacityRejections": 0,
                "releaseP95MaxRatio": MAX_RELEASE_P95_RATIO,
                "releaseP95MaxDeltaMs": MAX_RELEASE_P95_DELTA_MS,
                "mediaP95MaxRatio": MAX_MEDIA_P95_RATIO,
                "mediaP95MaxDeltaMs": MAX_MEDIA_P95_DELTA_MS,
                "mediaRecoveryMaxRatio": MAX_MEDIA_RECOVERY_RATIO,
                "mediaRecoveryMaxDeltaMs": MAX_MEDIA_RECOVERY_DELTA_MS,
            },
            "status": "external_gate" if reasons else "passed",
            "reasonCodes": reasons,
            "releaseWindowMinutes": 30,
            "releaseWindows": release_windows,
            "loadCurve": load_curve,
            "mediaContention": media_contention,
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate local exported production performance evidence"
    )
    parser.add_argument("--monitor-sqlite", type=Path, required=True)
    parser.add_argument("--deployment-jsonl", type=Path, required=True)
    parser.add_argument("--load-curve", type=Path, required=True)
    parser.add_argument("--media-contention", type=Path, required=True)
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    as_of = _parse_time(args.as_of) if args.as_of else dt.datetime.now(UTC)
    try:
        report = evaluate_production_evidence(
            monitor_path=args.monitor_sqlite,
            deployment_path=args.deployment_jsonl,
            load_curve_path=args.load_curve,
            media_contention_path=args.media_contention,
            as_of=as_of,
        )
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}))
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
