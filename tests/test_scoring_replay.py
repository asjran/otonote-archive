import json
import tempfile
import unittest
from pathlib import Path

from tools.scoring_replay import load_replays, summarize_replays, validate_replay


class ScoringReplayTest(unittest.TestCase):
    def replay(self, status: str = "fixture") -> dict:
        return {
            "schemaVersion": 1,
            "sampleId": "sample-1",
            "sourceReleaseId": "release-1",
            "ruleSetVersion": "rules-1",
            "verificationStatus": status,
            "sourceEvidence": ["client-log"] if status == "reconciled" else [],
            "formation": {"totalPower": 1234},
            "judgements": [],
            "scoreCommands": [],
            "chart": {
                "events": [
                    {
                        "id": "note-1",
                        "notePercent": 10,
                        "judgementPercent": 100,
                        "comboPercent": 100,
                        "scorePercent": 100,
                        "fixedScore": 0,
                    }
                ]
            },
            "expected": {"finalScore": 100},
        }

    def test_reconciled_sample_requires_client_evidence(self) -> None:
        replay = self.replay("reconciled")
        replay["sourceEvidence"] = []
        self.assertEqual(validate_replay(replay), ["client_evidence_required"])

    def test_requires_explicit_timeline_arrays(self) -> None:
        replay = self.replay()
        del replay["judgements"]
        del replay["scoreCommands"]
        self.assertEqual(
            validate_replay(replay),
            ["required_array:judgements", "required_array:scoreCommands"],
        )

    def test_loads_only_valid_versioned_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.json").write_text(
                json.dumps(self.replay()),
                encoding="utf-8",
            )
            replays = load_replays(root)
        self.assertEqual(len(replays), 1)
        self.assertEqual(replays[0]["sampleId"], "sample-1")

    def test_fixture_samples_keep_formal_capability_external(self) -> None:
        report = summarize_replays([self.replay()])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["sampleCount"], 1)
        self.assertEqual(report["statusCounts"]["fixture"], 1)
        self.assertEqual(report["formalCapability"], "external_gate")
        self.assertEqual(report["gate"], "client_replay_sample_missing")


if __name__ == "__main__":
    unittest.main()
