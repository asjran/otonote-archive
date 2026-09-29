import json
import tempfile
import unittest
from pathlib import Path

from tools.scoring_evidence import (
    SCORING_RULE_SET_ID,
    build_scoring_evidence,
)


class ScoringEvidenceTests(unittest.TestCase):
    def _write_table(self, root: Path, name: str, rows: list[dict]) -> None:
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": rows}),
            encoding="utf-8",
        )

    def test_builds_a_blocked_versioned_manifest_from_master_and_native_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_table(
                root,
                "MasterLiveComboScoreBonus",
                [
                    {"_comboBonusType": 0, "_requiredComboCount": 10, "_bonusFactor": 0.01},
                    {"_comboBonusType": 0, "_requiredComboCount": 20, "_bonusFactor": 0.005},
                    {"_comboBonusType": 1, "_requiredComboCount": 10, "_bonusFactor": 0.01},
                ],
            )
            self._write_table(
                root,
                "MasterLiveScoreRank",
                [
                    {"_group": 100, "_liveScoreRank": 2, "_requiredScore": 0},
                    {"_group": 100, "_liveScoreRank": 3, "_requiredScore": 1000},
                ],
            )
            self._write_table(
                root,
                "MasterLiveSkillEffect",
                [
                    {"_skillEffectType": 2000},
                    {"_skillEffectType": 2000},
                    {"_skillEffectType": 3001},
                ],
            )
            methods = [
                {
                    "assembly": "App.LiveLogic.Score.Runtime.dll",
                    "typeName": "App.LiveLogic.Score.LiveScoreCalculator",
                    "methodName": "CalcNoteScoreCore",
                    "parameterCount": 6,
                    "token": 0x060000B1,
                    "address": 0x1234,
                },
                {
                    "assembly": "App.Runtime.dll",
                    "typeName": "App.UI.BattleLiveLog.PlayerFormationPowerCalculator",
                    "methodName": "CalculateLeaderSkillBonuses",
                    "parameterCount": 4,
                    "token": 0x060082AE,
                    "address": 0x5678,
                },
            ]

            result = build_scoring_evidence(root, methods, "test-release")

        self.assertEqual(result["ruleSet"]["id"], SCORING_RULE_SET_ID)
        self.assertEqual(result["capability"]["status"], "blocked")
        self.assertFalse(result["capability"]["producesFormalScore"])
        self.assertEqual(result["masterEvidence"]["comboBonus"]["rowCount"], 3)
        self.assertEqual(
            result["masterEvidence"]["comboBonus"]["types"][0]["factors"],
            [0.005, 0.01],
        )
        self.assertEqual(result["masterEvidence"]["scoreRank"]["groupCount"], 1)
        self.assertEqual(
            result["masterEvidence"]["skillEffect"]["effectTypeCounts"],
            {"2000": 2, "3001": 1},
        )
        self.assertIn("note_score_core", result["knownMechanisms"])
        self.assertIn("leader_power_bonus", result["knownMechanisms"])
        self.assertIn("two_stage_floor_rounding", result["knownMechanisms"])
        self.assertEqual(
            result["staticAnalysis"][0]["observations"]["floorStageCount"],
            2,
        )
        self.assertEqual(result["validationGate"]["replaySampleCount"], 0)
        self.assertFalse(result["validationGate"]["exactIntegerReconciliation"])

    def test_native_addresses_are_not_published_as_part_of_the_evidence_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_table(root, "MasterLiveComboScoreBonus", [])
            self._write_table(root, "MasterLiveScoreRank", [])
            self._write_table(root, "MasterLiveSkillEffect", [])
            result = build_scoring_evidence(
                root,
                [
                    {
                        "assembly": "App.LiveLogic.Score.Runtime.dll",
                        "typeName": "App.LiveLogic.Score.LiveScoreCalculator",
                        "methodName": "Calculate",
                        "parameterCount": 1,
                        "token": 0x060000A0,
                        "address": 0xDEADBEEF,
                    }
                ],
                "test-release",
            )

        serialized = json.dumps(result)
        self.assertNotIn("address", serialized)
        self.assertNotIn("3735928559", serialized)

    def test_reports_fixture_replay_without_opening_formal_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_table(root, "MasterLiveComboScoreBonus", [])
            self._write_table(root, "MasterLiveScoreRank", [])
            self._write_table(root, "MasterLiveSkillEffect", [])
            result = build_scoring_evidence(
                root,
                [],
                "test-release",
                {
                    "sampleCount": 1,
                    "statusCounts": {
                        "fixture": 1,
                        "observed": 0,
                        "reconciled": 0,
                        "rejected": 0,
                    },
                    "formalCapability": "external_gate",
                    "gate": "client_replay_sample_missing",
                },
            )

        gate = result["validationGate"]
        self.assertEqual(gate["fixtureReplayCount"], 1)
        self.assertEqual(gate["replaySampleCount"], 0)
        self.assertTrue(gate["inputSnapshotReplayable"])
        self.assertEqual(gate["formalCapability"], "external_gate")


if __name__ == "__main__":
    unittest.main()
