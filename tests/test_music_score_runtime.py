from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.music_score_runtime import compile_music_score
from tools.build_site_catalog import compare_published_music_timelines


MASTER_ROOT = REPO_ROOT / "phone_dump/crypto/master-json"
SCORE_ROOT = REPO_ROOT / "phone_dump/device_current_extracted/textassets"


def _master_rows(name: str) -> list[dict[str, object]]:
    value = json.loads((MASTER_ROOT / f"{name}.json").read_text(encoding="utf-8"))
    return value["_allData"]


def _score_payload(logical_name: str) -> bytes:
    basename = logical_name.rsplit("/", 1)[-1]
    matches = list(SCORE_ROOT.glob(f"*_{basename}.bin"))
    if len(matches) != 1:
        raise AssertionError(
            f"{logical_name} resolved to {len(matches)} extracted payloads"
        )
    return matches[0].read_bytes()


@unittest.skipUnless(
    (MASTER_ROOT / "MasterLiveMusicScore.json").is_file()
    and SCORE_ROOT.is_dir(),
    "local full-score evidence is unavailable",
)
class MusicScoreRuntimeAcceptanceTest(unittest.TestCase):
    def test_three_measured_expert_charts_match_the_game(self) -> None:
        goldens = {
            "0040/0040_03": 1054,
            "0054/0054_03": 827,
            "0051/0051_03": 856,
        }

        for logical_name, expected in goldens.items():
            with self.subTest(score=logical_name):
                projection = compile_music_score(_score_payload(logical_name))
                self.assertEqual(
                    projection["statistics"]["runtimeFullCombo"],
                    expected,
                )

    def test_masquerade_keeps_the_measured_local_timeline_and_merge_reason(
        self,
    ) -> None:
        projection = compile_music_score(_score_payload("0040/0040_03"))
        events = {
            event["combo"]: event for event in projection["comboEvents"]
        }
        self.assertEqual(
            (
                events[130]["time"],
                events[130]["noteId"],
                events[130]["kind"],
            ),
            (21.789, "note-694", "slide-combo"),
        )
        self.assertEqual(
            [
                (
                    events[combo]["time"],
                    events[combo]["noteId"],
                    events[combo]["kind"],
                )
                for combo in range(689, 703)
            ],
            [
                (75.947368, "note-542", "explicit-judgement"),
                (76.105263, "note-697", "explicit-judgement"),
                (76.105263, "note-90", "explicit-judgement"),
                (76.263158, "note-170", "explicit-judgement"),
                (76.342105, "note-156", "explicit-judgement"),
                (76.421053, "note-57", "explicit-judgement"),
                (76.578947, "note-540", "explicit-judgement"),
                (76.578947, "note-71", "explicit-judgement"),
                (76.736842, "note-198", "explicit-judgement"),
                (76.736842, "note-541", "explicit-judgement"),
                (76.894737, "note-50", "explicit-judgement"),
                (77.052632, "note-543", "explicit-judgement"),
                (77.052632, "note-698", "explicit-judgement"),
                (77.21, "note-698", "slide-combo"),
            ],
        )
        diagnostics = projection["statistics"]["runtimeDiagnostics"]
        self.assertIn(
            {
                "kind": "skip",
                "reason": "converging-slide",
                "noteId": "note-694",
                "time": 21.947,
                "overlap": 3.246498,
            },
            diagnostics,
        )
        self.assertIn(
            {
                "kind": "merge",
                "reason": "identical-slide-endpoint",
                "time": 22.105263,
                "markerIds": ["note-639:1", "note-694:1"],
            },
            diagnostics,
        )

    def test_all_formal_charts_compile_deterministically_and_conserve_combo(
        self,
    ) -> None:
        score_rows = _master_rows("MasterLiveMusicScore")
        self.assertEqual(len(score_rows), 132)

        for row in score_rows:
            logical_name = str(row["_musicScoreTextFileName"])
            with self.subTest(score=logical_name):
                payload = _score_payload(logical_name)
                first = compile_music_score(payload)
                second = compile_music_score(payload)
                self.assertEqual(first, second)

                statistics = first["statistics"]
                expected = (
                    statistics["explicitJudgementCount"]
                    + statistics["slideComboCandidateCount"]
                    - statistics["skippedSlideComboCount"]
                    - statistics["mergedEndpointReduction"]
                )
                self.assertEqual(statistics["runtimeFullCombo"], expected)
                self.assertEqual(
                    [event["combo"] for event in first["comboEvents"]],
                    list(range(1, expected + 1)),
                )
                self.assertEqual(
                    sum(bucket["count"] for bucket in first["density"]),
                    expected,
                )
                guide_ids = {
                    note["id"]
                    for note in first["notes"]
                    if note["type"] == "guide"
                }
                self.assertTrue(
                    all(
                        event["noteId"] not in guide_ids
                        for event in first["comboEvents"]
                    )
                )


class MusicScoreRuntimeEdgeCaseTest(unittest.TestCase):
    def test_invisible_matching_endpoints_do_not_reduce_combo(self) -> None:
        score = {
            "meta": {"version": 100},
            "score": {
                "events": {"bpm": [{"t": 0, "bpm": 120}]},
                "notes": [
                    {
                        "type": "long",
                        "node": [
                            {"t": 0, "pos": 0, "size": 2},
                            {"t": 1, "pos": 10, "size": 4, "visible": False},
                        ],
                    },
                    {
                        "type": "long",
                        "node": [
                            {"t": 0, "pos": 6, "size": 2},
                            {"t": 1, "pos": 10, "size": 4, "visible": False},
                        ],
                    },
                ],
            },
        }
        projection = compile_music_score(gzip.compress(json.dumps(score).encode()))
        self.assertEqual(projection["statistics"]["runtimeFullCombo"], 2)
        self.assertEqual(
            projection["statistics"]["mergedEndpointReduction"], 0
        )


class MusicScoreRuntimeReportTest(unittest.TestCase):
    def test_equal_fc_with_changed_events_has_its_own_classification(self) -> None:
        report = {
            "musicScoreRuntimeReport": [
                {
                    "chartId": "music-chart-1",
                    "classification": "MATCH",
                    "firstTimelineDifference": None,
                }
            ]
        }
        current = {
            "music-chart-1": {
                "comboEvents": [
                    {
                        "time": 0.5,
                        "markerId": "note-1",
                        "noteId": "note-1",
                        "nodeIndex": None,
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "music-chart-1.json").write_text(
                json.dumps(
                    {
                        "comboEvents": [
                            {
                                "time": 0.25,
                                "markerId": "note-1",
                                "noteId": "note-1",
                                "nodeIndex": None,
                            }
                        ],
                        "statistics": {"judgementCount": 1},
                    }
                ),
                encoding="utf-8",
            )
            compare_published_music_timelines(report, current, root)

        row = report["musicScoreRuntimeReport"][0]
        self.assertEqual(row["classification"], "TIMELINE_CHANGED_ONLY")
        self.assertEqual(row["firstTimelineDifference"]["combo"], 1)
        self.assertTrue(row["requiresManualReview"])
        self.assertEqual(
            report["musicScoreRuntimeClassificationCounts"][
                "TIMELINE_CHANGED_ONLY"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
