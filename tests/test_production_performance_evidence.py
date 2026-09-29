from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.production_performance_evidence import (
    _media_contention_evidence,
    evaluate_foundation_evidence,
    evaluate_production_evidence,
    stabilize_reason_codes,
)


UTC = dt.timezone.utc


def _write_monitor_fixture(
    path: Path,
    *,
    as_of: dt.datetime,
    days: int,
    stale_heartbeat: bool,
    create_gap: bool,
) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE minute_metrics (
          bucket TEXT NOT NULL,
          category TEXT NOT NULL,
          status INTEGER NOT NULL,
          protocol TEXT NOT NULL,
          requests INTEGER NOT NULL,
          bytes INTEGER NOT NULL,
          total_ms REAL NOT NULL,
          range_requests INTEGER NOT NULL,
          not_modified INTEGER NOT NULL,
          errors INTEGER NOT NULL,
          PRIMARY KEY (bucket, category, status, protocol)
        );
        CREATE TABLE latency_histogram (
          bucket TEXT NOT NULL,
          category TEXT NOT NULL,
          upper_ms INTEGER NOT NULL,
          requests INTEGER NOT NULL,
          PRIMARY KEY (bucket, category, upper_ms)
        );
        CREATE TABLE outcome_metrics (
          bucket TEXT NOT NULL,
          outcome TEXT NOT NULL,
          status INTEGER NOT NULL,
          requests INTEGER NOT NULL,
          bytes INTEGER NOT NULL,
          PRIMARY KEY (bucket, outcome, status)
        );
        """
    )
    heartbeat = as_of - dt.timedelta(hours=2 if stale_heartbeat else 0, minutes=5)
    db.executemany(
        "INSERT INTO meta(key, value) VALUES(?, ?)",
        [
            ("schema_version", "3"),
            ("last_success", heartbeat.isoformat().replace("+00:00", "Z")),
        ],
    )
    first_day = as_of.date() - dt.timedelta(days=7)
    for day_offset in range(days):
        day = first_day + dt.timedelta(days=day_offset)
        for minute in range(0, 24 * 60, 30):
            if create_gap and day_offset == 2 and minute in {600, 630}:
                continue
            bucket = dt.datetime.combine(day, dt.time(), UTC) + dt.timedelta(minutes=minute)
            db.execute(
                """INSERT INTO minute_metrics VALUES(?, 'page', 200, 'HTTP/2', 1, 100, 10, 0, 0, 0)""",
                (bucket.isoformat().replace("+00:00", "Z"),),
            )
            db.execute(
                """INSERT INTO latency_histogram VALUES(?, 'page', 25, 1)""",
                (bucket.isoformat().replace("+00:00", "Z"),),
            )
            db.execute(
                """INSERT INTO outcome_metrics VALUES(?, 'success', 200, 1, 100)""",
                (bucket.isoformat().replace("+00:00", "Z"),),
            )
    db.commit()
    db.close()


def _deployment_event(
    attempt: str,
    release: str,
    finished_at: str,
    *,
    result: str = "success",
    command: str = "deploy",
    environment: str = "production",
    transferred_bytes: int | None = 4096,
) -> dict[str, object]:
    rsync: dict[str, object] = {"transferredFiles": 2}
    if transferred_bytes is not None:
        rsync["transferredBytes"] = transferred_bytes
    return {
        "schemaVersion": 2,
        "attemptId": attempt,
        "command": command,
        "result": result,
        "environment": environment,
        "releaseId": release,
        "startedAt": finished_at,
        "finishedAt": finished_at,
        "disk": {"availableKiB": 2048},
        "rsync": rsync,
    }


class ProductionPerformanceEvidenceTest(unittest.TestCase):
    def test_media_contention_rejects_sustained_p95_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contention.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "scope": "production",
                        "controlled": True,
                        "media": {"rangeRequest": True},
                        "ordinaryPages": {
                            "requests": 120,
                            "errors": 0,
                            "p95BeforeMs": 100,
                            "p95DuringMs": 100_000,
                            "p95AfterMs": 99_999,
                        },
                    }
                ),
                encoding="utf-8",
            )

            _, reasons = _media_contention_evidence(path)

        self.assertIn("media_contention_p95_unbounded", reasons)
        self.assertIn("media_contention_p95_not_recovered", reasons)

    def test_reason_codes_are_stable_and_ordered_unique(self) -> None:
        self.assertEqual(
            stabilize_reason_codes(
                [
                    "production_load_curve_not_controlled",
                    "production_load_curve_not_get_only",
                    "production_load_curve_not_get_only",
                    "production_load_curve_incomplete",
                ]
            ),
            [
                "production_load_curve_not_controlled",
                "production_load_curve_not_get_only",
                "production_load_curve_incomplete",
            ],
        )

    def test_foundation_shortfalls_are_external_gates_not_program_errors(self) -> None:
        as_of = dt.datetime(2026, 8, 12, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            monitor = root / "monitor.sqlite3"
            deployments = root / "deployments.jsonl"
            _write_monitor_fixture(
                monitor,
                as_of=as_of,
                days=6,
                stale_heartbeat=True,
                create_gap=True,
            )
            events = [
                _deployment_event(
                    f"attempt-{index}",
                    f"release-2026080{index}",
                    f"2026-08-0{index + 4}T12:00:00Z",
                )
                for index in range(1, 5)
            ]
            events.extend(
                [
                    dict(events[0]),
                    _deployment_event("attempt-failed", "release-failed", "2026-08-09T12:00:00Z", result="failed"),
                    _deployment_event("attempt-rollback", "release-rollback", "2026-08-09T12:00:00Z", command="rollback"),
                    _deployment_event("attempt-local", "release-local", "2026-08-09T12:00:00Z", environment="local"),
                    _deployment_event("attempt-fixture", "release-fixture", "2026-08-09T12:00:00Z", environment="fixture"),
                    _deployment_event("attempt-placeholder", "unknown", "2026-08-09T12:00:00Z"),
                    _deployment_event("attempt-no-bytes", "release-no-bytes", "2026-08-09T12:00:00Z", transferred_bytes=None),
                ]
            )
            deployments.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )

            report = evaluate_foundation_evidence(
                monitor_path=monitor,
                deployment_path=deployments,
                as_of=as_of,
            )

        self.assertEqual(report["status"], "external_gate")
        self.assertEqual(
            report["reasonCodes"],
            [
                "monitor_complete_days_insufficient",
                "monitor_heartbeat_stale",
                "monitor_collection_gap",
                "deployment_real_successes_insufficient",
            ],
        )
        self.assertEqual(report["monitor"]["completeNaturalDays"], 3)
        self.assertGreater(report["monitor"]["maxGapMinutes"], 60)
        self.assertEqual(report["deployments"]["realSuccessCount"], 4)
        self.assertEqual(report["deployments"]["uniqueAttemptCount"], 10)
        self.assertEqual(report["deployments"]["excluded"]["missing_transfer_evidence"], 1)

    def test_complete_release_windows_curve_and_media_contention_pass(self) -> None:
        as_of = dt.datetime(2026, 8, 12, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            monitor = root / "monitor.sqlite3"
            deployments = root / "deployments.jsonl"
            curve = root / "production-curve.json"
            contention = root / "media-contention.json"
            _write_monitor_fixture(
                monitor,
                as_of=as_of,
                days=7,
                stale_heartbeat=False,
                create_gap=False,
            )
            events = [
                _deployment_event(
                    f"attempt-{index}",
                    f"release-202608{index:02d}",
                    f"2026-08-{index + 4:02d}T12:00:00Z",
                )
                for index in range(1, 6)
            ]
            deployments.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            curve.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "scope": "production",
                        "controlled": True,
                        "routeSummary": {"method": "GET", "count": 6},
                        "stages": [
                            {
                                "concurrency": concurrency,
                                "requests": requests,
                                "summary": {
                                    "failures": 0,
                                    "errorRate": 0,
                                    "requestsPerSecond": 100,
                                    "ttfbMs": {"p50": 10, "p95": 20, "p99": 30},
                                    "totalMs": {"p50": 20, "p95": 40, "p99": 60},
                                },
                            }
                            for concurrency, requests in (
                                (5, 100),
                                (10, 200),
                                (20, 200),
                                (50, 100),
                            )
                        ],
                    }
                ),
                encoding="utf-8",
            )
            contention.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "scope": "production",
                        "controlled": True,
                        "media": {"rangeRequest": True},
                        "ordinaryPages": {
                            "requests": 120,
                            "errors": 0,
                            "p95BeforeMs": 100,
                            "p95DuringMs": 140,
                            "p95AfterMs": 105,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_production_evidence(
                monitor_path=monitor,
                deployment_path=deployments,
                load_curve_path=curve,
                media_contention_path=contention,
                as_of=as_of,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["generatedAt"], as_of.isoformat())
        self.assertEqual(report["asOf"], as_of.isoformat())
        self.assertEqual(set(report["inputs"]), {
            "monitorSha256", "deploymentSha256", "loadCurveSha256",
            "mediaContentionSha256",
        })
        self.assertTrue(all(len(value) == 64 for value in report["inputs"].values()))
        self.assertEqual(report["thresholds"]["releaseServer5xx"], 0)
        self.assertEqual(report["thresholds"]["mediaP95MaxRatio"], 2.0)
        self.assertEqual(report["reasonCodes"], [])
        self.assertEqual(len(report["releaseWindows"]), 5)
        for release in report["releaseWindows"]:
            for phase in ("before", "after"):
                window = release[phase]
                self.assertEqual(window["server5xx"], 0)
                self.assertEqual(window["capacityRejections"], 0)
                self.assertEqual(window["normalP95Ms"], 25)
                self.assertEqual(window["categoryBytes"], {"page": 100})
                self.assertGreater(window["peakMbps"], 0)
        self.assertEqual(report["loadCurve"]["stageConcurrencies"], [5, 10, 20, 50])
        self.assertEqual(report["mediaContention"]["ordinaryPageErrors"], 0)
        self.assertEqual(report["mediaContention"]["p95AfterMs"], 105)

    def test_release_window_errors_and_severe_p95_regression_block_passing(self) -> None:
        as_of = dt.datetime(2026, 8, 12, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            monitor = root / "monitor.sqlite3"
            deployments = root / "deployments.jsonl"
            curve = root / "curve.json"
            contention = root / "contention.json"
            _write_monitor_fixture(
                monitor, as_of=as_of, days=7, stale_heartbeat=False, create_gap=False
            )
            events = [
                _deployment_event(
                    f"attempt-{index}",
                    f"release-202608{index:02d}",
                    f"2026-08-{index + 4:02d}T12:00:00Z",
                )
                for index in range(1, 6)
            ]
            deployments.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            curve.write_text(json.dumps({
                "schemaVersion": 1,
                "scope": "production",
                "controlled": True,
                "routeSummary": {"method": "GET"},
                "stages": [
                    {"concurrency": concurrency, "requests": requests, "summary": {"failures": 0}}
                    for concurrency, requests in ((5, 100), (10, 200), (20, 200), (50, 100))
                ],
            }), encoding="utf-8")
            contention.write_text(json.dumps({
                "schemaVersion": 1,
                "scope": "production",
                "controlled": True,
                "media": {"rangeRequest": True},
                "ordinaryPages": {
                    "requests": 10, "errors": 0,
                    "p95BeforeMs": 100, "p95DuringMs": 120, "p95AfterMs": 100,
                },
            }), encoding="utf-8")
            db = sqlite3.connect(monitor)
            db.execute(
                "INSERT INTO outcome_metrics VALUES(?, 'server_error', 500, 1, 10)",
                ("2026-08-05T12:00:00Z",),
            )
            db.execute(
                "INSERT INTO outcome_metrics VALUES(?, 'capacity_rejection', 503, 1, 10)",
                ("2026-08-05T12:00:00Z",),
            )
            db.execute(
                "UPDATE latency_histogram SET upper_ms = 1000 WHERE bucket = ?",
                ("2026-08-05T12:00:00Z",),
            )
            db.commit()
            db.close()

            report = evaluate_production_evidence(
                monitor_path=monitor,
                deployment_path=deployments,
                load_curve_path=curve,
                media_contention_path=contention,
                as_of=as_of,
            )

        self.assertEqual(report["status"], "external_gate")
        self.assertIn("release_window_server_5xx", report["reasonCodes"])
        self.assertIn("release_window_capacity_rejection", report["reasonCodes"])
        self.assertIn("release_window_p95_regression", report["reasonCodes"])

    def test_cli_returns_zero_for_external_gate_and_nonzero_for_unsupported_schema(self) -> None:
        as_of = dt.datetime(2026, 8, 12, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            monitor = root / "monitor.sqlite3"
            deployments = root / "deployments.jsonl"
            curve = root / "curve.json"
            contention = root / "contention.json"
            _write_monitor_fixture(
                monitor,
                as_of=as_of,
                days=1,
                stale_heartbeat=False,
                create_gap=False,
            )
            deployments.write_text("", encoding="utf-8")
            curve.write_text(
                json.dumps({"schemaVersion": 1, "stages": []}),
                encoding="utf-8",
            )
            contention.write_text(
                json.dumps({"schemaVersion": 1}),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "tools/production_performance_evidence.py"),
                "--monitor-sqlite",
                str(monitor),
                "--deployment-jsonl",
                str(deployments),
                "--load-curve",
                str(curve),
                "--media-contention",
                str(contention),
                "--as-of",
                as_of.isoformat(),
            ]

            external = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(external.returncode, 0, external.stderr)
            self.assertEqual(json.loads(external.stdout)["status"], "external_gate")

            curve.write_text(
                json.dumps({"schemaVersion": 2}),
                encoding="utf-8",
            )
            invalid = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(invalid.returncode, 2, invalid.stderr)
            self.assertEqual(json.loads(invalid.stdout)["status"], "invalid_input")

        source = (
            Path(__file__).resolve().parents[1]
            / "tools/production_performance_evidence.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("urllib", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("ssh", source.lower())


if __name__ == "__main__":
    unittest.main()
