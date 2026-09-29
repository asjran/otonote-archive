#!/usr/bin/env python3

import argparse
import json
import stat
import sqlite3
import subprocess
import sys
import tempfile
import datetime as dt
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise monitor collection, rendering, rotation and recovery")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[2] / "output/readiness/monitor.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        access = work / "access.log"
        database = work / "monitor.sqlite3"
        report = work / "report"
        deployment = work / "deployments.jsonl"
        config = work / "monitor.toml"
        config.write_text(
            f'[paths]\naccess_log = "{access}"\ndatabase = "{database}"\nreport_dir = "{report}"\ndeployment_log = "{deployment}"\n\n[privacy]\ndaily_salt = "fixture"\n',
            encoding="utf-8",
        )
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        timestamp = lambda minutes: (now - dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
        lifecycle_results = (
            "started", "success", "failed", "rollback_started",
            "rollback_succeeded", "rollback_failed",
        )
        deployment.write_text(
            "\n".join(json.dumps({
                "schemaVersion": 2,
                "attemptId": "fixture-attempt",
                "command": "rollback" if result.startswith("rollback_") else "deploy",
                "releaseId": "fixture-release",
                "gitCommit": "fixture-commit",
                "startedAt": timestamp(4),
                "finishedAt": timestamp(3),
                "result": result,
                "failedPhase": "health" if result in {"failed", "rollback_failed"} else None,
                "reasonCode": "fixture_failure" if result in {"failed", "rollback_failed"} else None,
                "phases": {"testsSeconds": 1, "artifactDiffSeconds": 1},
                "disk": {"availableKiB": 1024},
                "rsync": {"transferredFiles": 4, "matchedFiles": 6},
            }) for result in lifecycle_results) + "\nnot-json\n",
            encoding="utf-8",
        )
        lines = [
            {"time": timestamp(3), "path": "/", "status": 200, "bytes": 1000, "request_time": 0.02, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.1", "content_type": "text/html", "user_agent": "OurNotesSyntheticLoad/1.0"},
            {"time": timestamp(2), "path": "/media/music/sample.m4a", "status": 206, "bytes": 2000, "request_time": 0.12, "protocol": "HTTP/2.0", "range": "bytes=0-1999", "remote": "127.0.0.1", "content_type": "audio/mp4"},
            {"time": timestamp(1), "path": "/missing", "status": 404, "bytes": 10, "request_time": 0.01, "protocol": "HTTP/1.1", "range": "-", "remote": "127.0.0.2", "content_type": "text/html"},
            {"time": timestamp(1), "path": "/media/rejected.m4a", "status": 503, "bytes": 0, "request_time": 0.01, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.2", "content_type": "audio/mp4", "limit_conn_status": "REJECTED"},
            {"time": timestamp(1), "path": "/origin-failure", "status": 502, "bytes": 0, "request_time": 0.01, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.2", "content_type": "text/html"},
        ]
        access.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot-json\n", encoding="utf-8")
        collect = root / "tools/monitor/collect.py"
        render = root / "tools/monitor/render.py"
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        with access.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": timestamp(0), "path": "/cached", "status": 304, "bytes": 0, "request_time": 0.001, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.1", "content_type": "text/html"}) + "\n")
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        subprocess.run([sys.executable, render, "--config", config], check=True)
        rotated = work / "access.log.1"
        access.rename(rotated)
        access.write_text(
            json.dumps({"time": timestamp(0), "path": "/__health", "status": 200, "bytes": 5, "request_time": 0.005, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.1", "content_type": "text/plain"}) + "\n",
            encoding="utf-8",
        )
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        database.write_bytes(b"corrupt-database")
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        with access.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": timestamp(0), "path": "/after-recovery", "status": 200, "bytes": 20, "request_time": 0.04, "protocol": "HTTP/2.0", "range": "-", "remote": "127.0.0.3", "content_type": "text/html"}) + "\n")
        subprocess.run([sys.executable, collect, "--config", config], check=True)
        subprocess.run([sys.executable, render, "--config", config], check=True)
        db = sqlite3.connect(database)
        requests, sent, ranges, errors = db.execute(
            "SELECT SUM(requests), SUM(bytes), SUM(range_requests), SUM(errors) FROM minute_metrics"
        ).fetchone()
        assert (requests, sent, ranges, errors) == (8, 3035, 1, 3)
        meta = dict(db.execute("SELECT key, value FROM meta"))
        assert meta["invalid_lines"] == "1"
        assert meta["schema_version"] == "3"
        assert db.execute("SELECT SUM(requests) FROM minute_metrics WHERE category='synthetic'").fetchone()[0] == 1
        summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
        last_success = (report / "summary.json").read_bytes()
        broken_config = work / "broken-monitor.toml"
        broken_config.write_text(
            f'[paths]\naccess_log = "{access}"\ndatabase = "{work / "missing.sqlite3"}"\nreport_dir = "{report}"\n',
            encoding="utf-8",
        )
        failed_render = subprocess.run(
            [sys.executable, render, "--config", broken_config],
            capture_output=True,
        )
        assert failed_render.returncode != 0
        assert (report / "summary.json").read_bytes() == last_success
        assert summary["totals"]["requests"] == 8
        assert summary["totals"]["notModified"] == 1
        assert summary["real"]["requests"] == 6
        assert summary["real"]["pageViews"] == 4
        assert summary["real"]["visitors"] == 3
        assert summary["real"]["serverErrors"] == 1
        assert summary["synthetic"]["requests"] == 1
        assert summary["health"]["requests"] == 1
        assert set(summary["windows"]) == {"5m", "1h", "24h", "7d"}
        assert summary["windows"]["24h"]["traffic"]["largeMedia"]["requests"] == 2
        assert summary["windows"]["24h"]["traffic"]["synthetic"]["requests"] == 1
        assert summary["windows"]["24h"]["traffic"]["health"]["requests"] == 1
        assert summary["windows"]["24h"]["latencyMs"] == {"p50": 10, "p95": 250, "p99": 250}
        assert summary["outcomes"]["capacity_rejection"] == 1
        assert summary["outcomes"]["server_error"] == 1
        assert summary["deploymentEvents"]["attempts"][0]["attemptId"] == "fixture-attempt"
        assert set(summary["deploymentEvents"]["attempts"][0]["results"]) == set(lifecycle_results)
        assert summary["deploymentEvents"]["invalidLines"] == 1
        assert summary["status"]["code"] == "attention"
        assert (report / "index.html").exists()
        dashboard = (report / "index.html").read_text(encoding="utf-8")
        assert "真实页面访问" in dashboard
        assert "性能测试已单独计算" in dashboard
        assert "北京时间" in dashboard
        assert "这些数字是什么意思" in dashboard
        assert "P50/P95/P99" in dashboard
        assert "大媒体" in dashboard
        assert stat.S_IMODE((report / "index.html").stat().st_mode) == 0o644
        assert stat.S_IMODE((report / "summary.json").stat().st_mode) == 0o644
        assert stat.S_IMODE((report / "export.csv").stat().st_mode) == 0o644
        export = (report / "export.csv").read_text(encoding="utf-8")
        assert "p50Ms" in export
        assert "7d" in export
        assert "artifactDiffSeconds" in export
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schemaVersion": 3,
                    "status": "passed",
                    "windows": list(summary["windows"]),
                    "percentiles": ["p50", "p95", "p99"],
                    "trafficClasses": ["normal", "synthetic", "health", "largeMedia"],
                    "checks": ["malformed_line", "duplicate_consumption", "log_rotation", "sqlite_backup_restore", "migration_replay", "last_success_report", "capacity_rejection", "origin_error", "deployment_lifecycle"],
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    print("monitor fixture, replay and report checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
