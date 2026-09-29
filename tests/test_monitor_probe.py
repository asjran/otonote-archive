from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tools.monitor.probe import exit_code_for, run_probe


class FixtureClient:
    def check(self, url, *, timeout, range_header=None):
        return {
            "dnsMs": 2.0,
            "tcpMs": 3.0,
            "tlsMs": 4.0,
            "status": 206 if range_header else 200,
            "ttfbMs": 12.0,
            "totalMs": 15.0,
            "certificateDaysRemaining": 25,
            "acceptRanges": bool(range_header),
            "contentRange": "bytes 0-0/10" if range_header else None,
        }


class MonitorProbeTest(unittest.TestCase):
    def test_fixture_probe_emits_attention_contract_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "alerts.json"
            report = run_probe(
                {
                    "target": {"base_url": "https://example.test"},
                    "paths": {"homepage": "/", "representative": "/music/", "static": "/app.js", "media": "/sample.m4a"},
                    "thresholds": {"timeout_seconds": 5, "certificate_attention_days": 30, "certificate_incident_days": 7},
                    "output": {"alerts": str(output)},
                },
                client=FixtureClient(),
                now=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
            )
            self.assertEqual(report["target"], "https://example.test")
            self.assertEqual(report["severity"], "attention")
            self.assertEqual(report["failureCode"], "certificate_expiring")
            self.assertEqual(report["checks"]["media"]["range"]["valid"], True)
            self.assertEqual(exit_code_for(report), 1)
            self.assertTrue(output.is_file())

    def test_invalid_configuration_has_stable_exit_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "base_url"):
            run_probe({"target": {}}, client=FixtureClient())
        self.assertEqual(exit_code_for({"severity": "invalid_configuration"}), 3)


if __name__ == "__main__":
    unittest.main()
