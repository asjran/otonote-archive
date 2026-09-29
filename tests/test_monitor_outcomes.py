from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.monitor.collect import SCHEMA_VERSION, classify_outcome
from tools.monitor.render import calculate_monitor_freshness_minutes, evaluate_monitor_status


REPO_ROOT = Path(__file__).resolve().parents[1]


class MonitorOutcomeTest(unittest.TestCase):
    def test_calculates_freshness_from_python36_compatible_utc_timestamp(self) -> None:
        now = dt.datetime(2026, 8, 13, 7, 14, 42, 249428, tzinfo=dt.timezone.utc)

        self.assertEqual(
            calculate_monitor_freshness_minutes("2026-08-13T07:14:42.249428+00:00", now),
            0,
        )

    def test_thresholds_separate_incident_attention_capacity_and_freshness(self) -> None:
        normal_windows = {
            "5m": {"requests": 500, "outcomes": {"server_error": 2}},
            "1h": {"requests": 2000, "outcomes": {"server_error": 2}},
        }
        attention = evaluate_monitor_status(normal_windows, 0.2, 5, page_views=10)
        self.assertEqual(attention["code"], "attention")
        self.assertEqual([item["code"] for item in attention["alerts"]], ["origin_errors_observed"])

        incident_windows = {
            "5m": {"requests": 200, "outcomes": {"server_error": 3}},
            "1h": {"requests": 200, "outcomes": {"server_error": 3}},
        }
        incident = evaluate_monitor_status(incident_windows, 0.2, 5, page_views=10)
        self.assertEqual(incident["code"], "incident")
        self.assertIn("origin_error_rate_5m", [item["code"] for item in incident["alerts"]])

        capacity = evaluate_monitor_status(
            {"5m": {"requests": 20, "outcomes": {"capacity_rejection": 4}},
             "1h": {"requests": 20, "outcomes": {}}},
            0.2,
            5,
            page_views=10,
        )
        self.assertEqual(capacity["code"], "attention")
        self.assertEqual(capacity["alerts"][0]["code"], "capacity_rejection")

        stale = evaluate_monitor_status(normal_windows, 0.2, 21, page_views=10)
        self.assertEqual(stale["code"], "incident")
        self.assertIn("monitor_data_stale", [item["code"] for item in stale["alerts"]])

    def test_classifies_capacity_rejection_only_from_explicit_nginx_evidence(self) -> None:
        self.assertEqual(
            classify_outcome(503, "audio", "REJECTED", "PASSED"),
            "capacity_rejection",
        )
        self.assertEqual(classify_outcome(503, "audio", "", ""), "server_error")
        self.assertEqual(classify_outcome(404, "page", "", ""), "client_error")
        self.assertEqual(classify_outcome(200, "page", "", ""), "success")
        self.assertEqual(classify_outcome(200, "synthetic", "", ""), "synthetic")
        self.assertEqual(classify_outcome(200, "health", "", ""), "health")
        self.assertEqual(classify_outcome(599, "page", "", ""), "server_error_unclassified")

    def test_collector_migrates_v2_and_persists_outcomes_without_recounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            access = root / "access.log"
            database = root / "monitor.sqlite3"
            report = root / "report"
            config = root / "monitor.toml"
            config.write_text(
                '[paths]\naccess_log = "{}"\ndatabase = "{}"\nreport_dir = "{}"\n'
                '\n[privacy]\ndaily_salt = "fixture"\n'.format(access, database, report),
                encoding="utf-8",
            )
            db = sqlite3.connect(database)
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO meta VALUES('schema_version', '2')")
            db.commit()
            db.close()
            now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            rows = [
                {"time": now, "path": "/media/a.m4a", "status": 503, "bytes": 10,
                 "limit_conn_status": "REJECTED", "limit_req_status": "PASSED"},
                {"time": now, "path": "/old-503", "status": 503, "bytes": 20},
                {"time": now, "path": "/missing", "status": 404, "bytes": 30},
            ]
            access.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            command = [sys.executable, str(REPO_ROOT / "tools/monitor/collect.py"), "--config", str(config)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(command, check=True, capture_output=True, text=True)
            db = sqlite3.connect(database)
            try:
                outcomes = dict(db.execute("SELECT outcome, SUM(requests) FROM outcome_metrics GROUP BY outcome"))
                schema = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            finally:
                db.close()
            self.assertGreaterEqual(SCHEMA_VERSION, 3)
            self.assertEqual(schema, str(SCHEMA_VERSION))
            self.assertEqual(outcomes, {"capacity_rejection": 1, "client_error": 1, "server_error": 1})


if __name__ == "__main__":
    unittest.main()
