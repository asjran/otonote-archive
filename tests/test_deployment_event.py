from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.deployment_event import append_event, build_event


class DeploymentEventTest(unittest.TestCase):
    def test_builds_redacted_stable_lifecycle_event(self) -> None:
        event = build_event(
            attempt_id="attempt-1",
            command="deploy",
            result="failed",
            release_id="candidate-1",
            git_commit="abc123",
            started_at="2026-08-12T00:00:00Z",
            finished_at="2026-08-12T00:01:00Z",
            failed_phase="health",
            reason_code="public_health_failed",
            phases={"healthCheckSeconds": 60},
            disk={"availableKiB": 2048},
            rsync={"transferredFiles": 2, "matchedFiles": 8},
        )
        self.assertEqual(event["schemaVersion"], 2)
        self.assertEqual(event["attemptId"], "attempt-1")
        self.assertEqual(event["result"], "failed")
        self.assertEqual(event["failedPhase"], "health")
        self.assertNotIn("ssh", json.dumps(event).lower())
        self.assertNotIn("/Users/", json.dumps(event))

    def test_appends_all_six_lifecycle_results_as_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "events.jsonl"
            results = (
                "started", "success", "failed", "rollback_started",
                "rollback_succeeded", "rollback_failed",
            )
            for result in results:
                append_event(output, build_event(
                    attempt_id="attempt-1", command="deploy", result=result,
                    release_id="unknown", git_commit="unknown",
                    started_at="2026-08-12T00:00:00Z",
                    finished_at="2026-08-12T00:00:01Z",
                ))
            written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["result"] for item in written], list(results))


if __name__ == "__main__":
    unittest.main()
