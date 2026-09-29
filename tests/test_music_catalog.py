from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.music_catalog import (
    MusicCatalogError,
    build_music_catalog,
    collect_score_payloads,
)


class MusicCatalogTest(unittest.TestCase):
    def test_collects_nonempty_exported_binary_score_by_logical_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exported = root / "textassets" / "score.bin"
            exported.parent.mkdir()
            exported.write_bytes(b"\x1f\x8bscore")
            payloads = collect_score_payloads(
                {
                    "assets": [
                        {
                            "type": "TextAsset",
                            "container_path": (
                                "Assets/AddressableResources/Live/"
                                "MusicScore/0001/0001_03.bytes"
                            ),
                            "exported_file": "textassets/score.bin",
                        }
                    ]
                },
                root,
                root,
            )

            self.assertEqual(payloads, {"0001/0001_03.bytes": b"\x1f\x8bscore"})

    def test_builds_track_and_four_difficulties_from_explicit_master_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def write_table(name: str, rows: list[dict[str, object]]) -> None:
                (root / f"{name}.json").write_text(
                    json.dumps({"_allData": rows}),
                    encoding="utf-8",
                )

            write_table(
                "MasterLiveMusic",
                [
                    {
                        "_id": 100001,
                        "_titleTextID": "title",
                        "_phoneticTextID": "phonetic",
                        "_rubyTitleTextID": "ruby",
                        "_sortOrder": 20,
                        "_bandIDs": [1],
                        "_vocalCharacterIDs": [1],
                        "_musicType": 1,
                        "_musicCategories": [1],
                        "_bestMusicTagIDs": [1],
                        "_musicSoundID": 1301,
                        "_jingleSoundID": 1401,
                        "_easyID": 41,
                        "_normalID": 17,
                        "_hardID": 88,
                        "_expertID": 9,
                        "_liveScoreRankGroup": 1100001,
                        "_scoreRankRewardGroup": 1,
                        "_comboRewardGroup": 1,
                        "_scoreCLiveMusicRewardID": 1,
                        "_scoreBLiveMusicRewardID": 2,
                        "_scoreALiveMusicRewardID": 3,
                        "_scoreSLiveMusicRewardID": 4,
                        "_scoreSSLiveMusicRewardID": 5,
                        "_comboEasyLiveMusicRewardID": 6,
                        "_comboNormalLiveMusicRewardID": 7,
                        "_comboHardLiveMusicRewardID": 8,
                        "_comboExpertLiveMusicRewardID": 9,
                        "_gekisouMission1": 1,
                        "_gekisouMission2": 2,
                        "_gekisouMission3": 3,
                        "_startAt": "2025/01/01 0:00:00",
                        "_lyricistTextID": "lyricist",
                        "_composerTextID": "composer",
                        "_arrangerTextID": "arranger",
                        "_jacketAssetName": "jkt_001_100001",
                    }
                ],
            )
            write_table(
                "MasterLiveMusicScore",
                [
                    {
                        "_id": score_id,
                        "_musicScoreTextFileName": path,
                        "_musicScoreLevel": level,
                        "_musicScoreDisplayLevel": float(level),
                        "_fullComboCount": full_combo,
                    }
                    for score_id, path, level, full_combo in (
                        (41, "0001/0001_00", 10, 100),
                        (17, "0001/0001_01", 14, 200),
                        (88, "0001/0001_02", 20, 300),
                        (9, "0001/0001_03", 27, 818),
                    )
                ],
            )
            write_table(
                "MasterLiveMusicCategory",
                [{"_id": 1, "_musicCategories": [1], "_textKey": "category"}],
            )
            write_table(
                "MasterLiveScoreRank",
                [
                    {
                        "_id": rank,
                        "_group": 1100001,
                        "_liveScoreRank": rank,
                        "_requiredScore": required_score,
                        "_battleLiveRequiredScore": 0,
                    }
                    for rank, required_score in (
                        (2, 0),
                        (3, 553524),
                        (4, 2136175),
                        (5, 4548528),
                        (6, 9150398),
                        (7, 12945117),
                    )
                ],
            )
            write_table(
                "MasterLiveFreeReward",
                [
                    {
                        "_id": group,
                        "_group": group,
                        "_liveScoreRank": 7,
                        "_resourceType": 1,
                        "_resourceId": group + 2,
                        "_resourceCount": group * 100,
                        "_probability": 10000,
                    }
                    for group in range(1, 10)
                ],
            )
            write_table(
                "MasterLiveMusicScoreReward",
                [
                    {
                        "_id": rank,
                        "_group": 1,
                        "_liveScoreRank": rank,
                        "_resourceType": 1,
                        "_resourceId": 1,
                        "_resourceCount": count,
                    }
                    for rank, count in (
                        (3, 5),
                        (4, 10),
                        (5, 15),
                        (6, 25),
                        (7, 50),
                    )
                ],
            )
            write_table(
                "MasterLiveMusicComboReward",
                [
                    {
                        "_id": difficulty * 4 + combo_rate + 1,
                        "_group": 1,
                        "_difficulty": difficulty,
                        "_comboRateType": combo_rate,
                        "_resourceType": 1,
                        "_resourceId": 3 if combo_rate < 2 else 1,
                        "_resourceCount": (difficulty + 1) * (combo_rate + 1) * 500,
                    }
                    for difficulty in range(4)
                    for combo_rate in range(4)
                ],
            )
            write_table(
                "MasterTag",
                [{"_id": 1, "_nameTextID": "band"}],
            )
            write_table(
                "MasterBand",
                [{"_id": 1, "_nameTextID": "band"}],
            )
            write_table(
                "MasterCharacter",
                [{"_id": 1, "_nameTextID": "character", "_bandID": 1}],
            )
            write_table(
                "MasterLiveCharacter",
                [{"_id": 1, "_characterID": 1}],
            )
            write_table(
                "MasterText",
                [
                    {"_id": key, "_japanese": value}
                    for key, value in (
                        ("title", "迷星叫"),
                        ("phonetic", "まよいうた"),
                        ("ruby", "迷星叫"),
                        ("lyricist", "藤原優樹"),
                        ("composer", "長谷川大介"),
                        ("arranger", "長谷川大介"),
                        ("category", "オリジナル"),
                        ("band", "MyGO!!!!!"),
                        ("character", "高松燈"),
                    )
                ],
            )

            raw_score = gzip.compress(
                json.dumps(
                    {
                        "meta": {"version": 100},
                        "score": {
                            "events": {
                                "bpm": [{"t": 0, "bpm": 190}],
                                "sig": [{"t": 0, "sig": [4, 4]}],
                                "skill": [],
                                "fever": [],
                                "call": [],
                            },
                            "notes": [
                                {
                                    "type": "long",
                                    "node": [
                                        {"t": 0, "pos": 2, "size": 3},
                                        {"t": 196080, "pos": 4, "size": 3},
                                    ],
                                }
                            ],
                        },
                    }
                ).encode("utf-8"),
                mtime=0,
            )
            payloads = {
                f"{path}.bytes": raw_score
                for path in (
                    "0001/0001_00",
                    "0001/0001_01",
                    "0001/0001_02",
                    "0001/0001_03",
                )
            }

            result = build_music_catalog(
                root,
                payloads,
                {"jkt_001_100001": "asset-jacket"},
                "staging-1",
            )

            self.assertEqual(len(result.tracks), 1)
            self.assertEqual(len(result.charts), 4)
            track = result.tracks[0]
            self.assertEqual(track["id"], "music-100001")
            self.assertEqual(track["title"], "迷星叫")
            self.assertEqual(track["chartIds"], [
                "music-chart-41",
                "music-chart-17",
                "music-chart-88",
                "music-chart-9",
            ])
            self.assertEqual(track["jacketAssetId"], "asset-jacket")
            self.assertEqual(
                track["gekisouMissions"],
                [
                    {
                        "index": 1,
                        "typeCode": 1,
                        "type": "combo",
                        "label": "COMBO",
                        "sourceField": "_gekisouMission1",
                        "evidenceStatus": "confirmed-data",
                    },
                    {
                        "index": 2,
                        "typeCode": 2,
                        "type": "luck",
                        "label": "LUCK",
                        "sourceField": "_gekisouMission2",
                        "evidenceStatus": "confirmed-data",
                    },
                    {
                        "index": 3,
                        "typeCode": 3,
                        "type": "just",
                        "label": "JUST",
                        "sourceField": "_gekisouMission3",
                        "evidenceStatus": "confirmed-data",
                    },
                ],
            )
            self.assertEqual(
                track["soloRewards"]["scoreRanks"],
                [
                    {"rank": 2, "requiredScore": 0},
                    {"rank": 3, "requiredScore": 553524},
                    {"rank": 4, "requiredScore": 2136175},
                    {"rank": 5, "requiredScore": 4548528},
                    {"rank": 6, "requiredScore": 9150398},
                    {"rank": 7, "requiredScore": 12945117},
                ],
            )
            self.assertEqual(
                track["soloRewards"]["scoreRewards"][0],
                {
                    "liveScoreRank": 3,
                    "requiredScore": 553524,
                    "entry": {
                        "resourceType": 1,
                        "resourceId": 1,
                        "resourceCount": 5,
                    },
                },
            )
            self.assertEqual(
                [entry["difficulty"] for entry in track["soloRewards"]["comboRewards"]],
                [
                    "easy",
                    "easy",
                    "easy",
                    "easy",
                    "normal",
                    "normal",
                    "normal",
                    "normal",
                    "hard",
                    "hard",
                    "hard",
                    "hard",
                    "expert",
                    "expert",
                    "expert",
                    "expert",
                ],
            )
            self.assertEqual(
                track["soloRewards"]["comboRewards"][-1],
                {
                    "difficulty": "expert",
                    "comboRateType": 3,
                    "entry": {
                        "resourceType": 1,
                        "resourceId": 1,
                        "resourceCount": 8000,
                    },
                },
            )
            expert = next(
                chart for chart in result.charts if chart["difficulty"] == "expert"
            )
            self.assertEqual(expert["masterId"], 9)
            self.assertEqual(expert["level"], 27)
            self.assertEqual(expert["fullComboCount"], 818)
            self.assertEqual(expert["judgementCount"], 818)
            self.assertEqual(
                expert["judgementCountSource"],
                "client-runtime-reconstruction",
            )
            self.assertEqual(expert["masterFullComboCount"], 818)
            self.assertEqual(expert["fullComboDelta"], 0)
            self.assertEqual(expert["fullComboClassification"], "MATCH")
            self.assertEqual(expert["fullComboStatus"], "match")
            self.assertEqual(
                expert["runtimeAlgorithmVersion"],
                "ss-runtime-v1",
            )
            easy = next(
                chart
                for chart in result.charts
                if chart["difficulty"] == "easy"
            )
            self.assertEqual(easy["fullComboCount"], 818)
            self.assertEqual(easy["masterFullComboCount"], 100)
            self.assertEqual(easy["fullComboClassification"], "RUNTIME_HIGHER")
            self.assertEqual(
                expert["analysisDataUrl"],
                "/data/music-charts/music-chart-9.json",
            )
            self.assertFalse(
                any("Full Combo" in warning for warning in result.warnings)
            )
            self.assertEqual(
                result.chart_data["music-chart-9"]["statistics"][
                    "sourceJudgementCount"
                ],
                2,
            )

    def test_rejects_missing_explicit_difficulty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, rows in {
                "MasterLiveMusic": [
                    {
                        "_id": 1,
                        "_titleTextID": "title",
                        "_easyID": 1,
                        "_normalID": 2,
                        "_hardID": 3,
                        "_expertID": 4,
                    }
                ],
                "MasterLiveMusicScore": [],
                "MasterLiveMusicCategory": [],
                "MasterLiveScoreRank": [],
                "MasterLiveFreeReward": [],
                "MasterLiveMusicScoreReward": [],
                "MasterLiveMusicComboReward": [],
                "MasterTag": [],
                "MasterBand": [],
                "MasterCharacter": [],
                "MasterLiveCharacter": [],
                "MasterText": [{"_id": "title", "_japanese": "Track"}],
            }.items():
                (root / f"{name}.json").write_text(
                    json.dumps({"_allData": rows}),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(MusicCatalogError, "easy difficulty 1"):
                build_music_catalog(root, {}, {}, "staging-1")


if __name__ == "__main__":
    unittest.main()
