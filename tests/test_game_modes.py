from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.game_modes import GameModeError, build_game_modes


REQUIRED_TABLES = (
    "MasterLiveScoreRank",
    "MasterBattleLiveReward",
    "MasterGekisouLiveRankReward",
    "MasterGekisouSkill",
    "MasterGekisouSkillEffect",
    "MasterGekisouSupportSkill",
    "MasterGekisouSupportSkillEffect",
    "MasterLiveGekisouMatchingBucket",
    "MasterLiveGekisouRankingScoreBonus",
    "MasterEvent",
    "MasterEventAchievementReward",
    "MasterEventRankingReward",
    "MasterEventEffect",
    "MasterEventPickUpCard",
    "MasterEventBoxGacha",
    "MasterEventBoxGachaReward",
)


def write_tables(
    root: Path,
    values: dict[str, list[dict[str, object]]],
) -> None:
    for name in REQUIRED_TABLES:
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": values.get(name, [])}),
            encoding="utf-8",
        )


class GameModeTest(unittest.TestCase):
    def test_rejects_missing_required_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                GameModeError,
                r"missing Master table: .*MasterBattleLiveReward\.json",
            ):
                build_game_modes(Path(temporary), "test-release")

    def test_builds_two_evidence_backed_mode_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterLiveScoreRank": [
                        {"_id": 1, "_group": 10, "_liveScoreRank": 2},
                        {"_id": 2, "_group": 10, "_liveScoreRank": 3},
                    ],
                    "MasterBattleLiveReward": [
                        {"_id": 1, "_group": 1, "_liveScoreRank": 7},
                        {"_id": 2, "_group": 1, "_liveScoreRank": 6},
                    ],
                    "MasterGekisouLiveRankReward": [
                        {
                            "_id": 1,
                            "_group": 4,
                            "_liveScoreRank": 7,
                            "_type": 1,
                        }
                    ],
                    "MasterGekisouSkill": [{"_id": 1}],
                    "MasterGekisouSkillEffect": [{"_id": 1}],
                    "MasterGekisouSupportSkill": [{"_id": 1}],
                    "MasterGekisouSupportSkillEffect": [{"_id": 1}],
                    "MasterLiveGekisouMatchingBucket": [
                        {"_id": 1, "_phase": 1, "_min": 0, "_max": 100}
                    ],
                    "MasterLiveGekisouRankingScoreBonus": [
                        {"_id": 1, "_rank": 1, "_scoreBonusPercent": 20}
                    ],
                },
            )

            result = build_game_modes(root, "test-release")

            self.assertEqual(result["sourceReleaseId"], "test-release")
            self.assertEqual(
                [mode["id"] for mode in result["modes"]],
                ["battle-live", "gekisou"],
            )
            self.assertEqual(result["modes"][0]["rewardSummary"]["rowCount"], 2)
            self.assertEqual(result["modes"][1]["aliases"], ["Gekisou", "激奏"])
            self.assertTrue(result["modes"][1]["capabilities"]["archive"])
            self.assertFalse(result["modes"][1]["capabilities"]["offlineSimulation"])
            self.assertFalse(result["modes"][0]["capabilities"]["onlineMultiplayer"])

    def test_event_routes_require_real_event_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterEventPickUpCard": [
                        {"_id": 1, "_eventId": 99},
                        {"_id": 2, "_eventId": 99},
                    ]
                },
            )

            result = build_game_modes(root, "test-release")
            events = result["events"]

            self.assertEqual(events["definitionCount"], 0)
            self.assertFalse(events["instanceRoutesEnabled"])
            self.assertEqual(events["orphanAuxiliaryRowCount"], 2)
            self.assertEqual(events["capabilities"], {
                "hasStory": False,
                "hasMode": False,
                "hasRewards": False,
                "hasRanking": False,
            })


if __name__ == "__main__":
    unittest.main()
