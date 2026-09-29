from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.high_score_rating import (
    HighScoreRatingError,
    build_high_score_rating,
)


def write_table(root: Path, name: str, rows: list[dict[str, object]]) -> None:
    (root / f"{name}.json").write_text(
        json.dumps({"_allData": rows}),
        encoding="utf-8",
    )


def rating_rows(multiplier: int = 1) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for grade in range(3):
        for step in range(6):
            index = grade * 6 + step
            rows.append(
                {
                    "_id": index + 1,
                    "_rating": index * 100 * multiplier,
                    "_grade": grade,
                    "_step": step,
                    "_liveMusicRewardIds": [] if index == 0 else [1],
                }
            )
    return rows


class HighScoreRatingBuildTest(unittest.TestCase):
    def build_fixture(self, root: Path) -> dict[str, object]:
        write_table(
            root,
            "MasterParameter",
            [
                {
                    "_id": "high_score_rating_top_music_count",
                    "_type": "Int32",
                    "_value": "20",
                }
            ],
        )
        write_table(root, "MasterLiveTotalHighScoreRating", rating_rows(5))
        band_rows = rating_rows(1)
        for row in band_rows:
            row["_bandId"] = 0
        write_table(root, "MasterLiveBandHighScoreRating", band_rows)
        write_table(
            root,
            "MasterReward",
            [
                {
                    "_id": 1,
                    "_resourceType": 1,
                    "_resourceId": 1,
                    "_resourceCount": 50,
                }
            ],
        )
        write_table(
            root,
            "MasterItem",
            [
                {
                    "_id": 1,
                    "_nameTextId": "Item_Name_1",
                }
            ],
        )
        write_table(
            root,
            "MasterText",
            [
                {
                    "_id": "Item_Name_1",
                    "_japanese": "スター",
                    "_simplifiedChinese": "",
                    "_english": "",
                }
            ],
        )
        return build_high_score_rating(root, "test-release")

    def test_builds_two_complete_strictly_increasing_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.build_fixture(Path(temporary))

        self.assertEqual(result["sourceReleaseId"], "test-release")
        self.assertEqual(result["topMusicCount"], 20)
        self.assertEqual(len(result["scopes"]["total"]["levels"]), 18)
        self.assertEqual(len(result["scopes"]["band"]["levels"]), 18)
        self.assertEqual(
            result["scopes"]["total"]["levels"][-1]["label"],
            "Gold V",
        )
        self.assertEqual(
            result["scopes"]["band"]["levels"][1]["rewardIds"],
            [1],
        )
        self.assertEqual(
            result["resolvedRewards"]["1"]["name"],
            "スター",
        )
        self.assertEqual(result["unresolvedRewardIds"], [])

    def test_rejects_missing_or_invalid_top_music_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_table(root, "MasterParameter", [])
            for name in (
                "MasterLiveTotalHighScoreRating",
                "MasterLiveBandHighScoreRating",
                "MasterReward",
                "MasterItem",
                "MasterText",
            ):
                write_table(root, name, [])
            with self.assertRaisesRegex(
                HighScoreRatingError,
                "high_score_rating_top_music_count",
            ):
                build_high_score_rating(root, "test-release")

    def test_rejects_duplicate_or_non_increasing_levels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.build_fixture(root)
            rows = rating_rows(5)
            rows[2]["_rating"] = rows[1]["_rating"]
            write_table(root, "MasterLiveTotalHighScoreRating", rows)

            with self.assertRaisesRegex(
                HighScoreRatingError,
                "strictly increasing",
            ):
                build_high_score_rating(root, "test-release")

    def test_records_unresolved_reward_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.build_fixture(root)
            rows = rating_rows(5)
            rows[-1]["_liveMusicRewardIds"] = [99]
            write_table(root, "MasterLiveTotalHighScoreRating", rows)
            result = build_high_score_rating(root, "test-release")

        self.assertEqual(result["unresolvedRewardIds"], [99])


if __name__ == "__main__":
    unittest.main()
