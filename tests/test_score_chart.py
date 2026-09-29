from __future__ import annotations

import gzip
import inspect
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.score_chart import ScoreChartError, parse_score_payload
from tools.music_score_runtime import compile_music_score


def score_payload(score: dict[str, object]) -> bytes:
    return gzip.compress(
        json.dumps(
            {"meta": {"version": 100}, "score": score},
            separators=(",", ":"),
        ).encode("utf-8"),
        mtime=0,
    )


class ScoreChartTest(unittest.TestCase):
    def test_normalizes_events_notes_and_multi_bpm_time(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [
                            {"t": 0, "bpm": 120},
                            {"t": 960, "bpm": 240},
                        ],
                        "sig": [{"t": 0, "sig": [4, 4]}],
                        "skill": [480],
                        "fever": [[480, 1440]],
                        "call": [{"t": 0, "timing": [0, 1]}],
                    },
                    "notes": [
                        {"t": 480, "pos": 2, "size": 3},
                        {
                            "type": "flick",
                            "t": 960,
                            "pos": 8,
                            "size": 4,
                            "dir": "right",
                        },
                        {
                            "type": "long",
                            "node": [
                                {
                                    "t": 960,
                                    "pos": 4,
                                    "size": 2,
                                    "ease": "out",
                                },
                                {
                                    "visible": False,
                                    "t": 1200,
                                    "pos": 5,
                                    "size": 2,
                                    "ease": "in",
                                },
                                {
                                    "t": 1440,
                                    "pos": 6,
                                    "size": 2,
                                },
                            ],
                        },
                    ],
                }
            )
        )

        self.assertEqual(chart["meta"]["tickResolution"], 480)
        self.assertEqual(chart["bpmEvents"][1]["time"], 1.0)
        self.assertEqual(chart["notes"][0]["time"], 0.5)
        self.assertEqual(chart["notes"][2]["nodes"][2]["time"], 1.25)
        self.assertEqual(chart["notes"][2]["nodes"][0]["easing"], "out")
        self.assertFalse(chart["notes"][2]["nodes"][1]["visible"])
        self.assertEqual(
            chart["statistics"]["noteCounts"],
            {"tap": 1, "flick": 1, "trace": 0, "long": 1},
        )
        self.assertEqual(chart["statistics"]["bpm"], {"min": 120.0, "max": 240.0})
        self.assertEqual(chart["skillTimings"], [0.5])
        self.assertEqual(chart["feverRanges"], [{"start": 0.5, "end": 1.25}])

    def test_rejects_invalid_or_unsupported_score_payloads(self) -> None:
        with self.assertRaisesRegex(ScoreChartError, "gzip"):
            parse_score_payload(b"not gzip")

        with self.assertRaisesRegex(ScoreChartError, "version"):
            parse_score_payload(
                gzip.compress(
                    json.dumps(
                        {
                            "meta": {"version": 999},
                            "score": {"events": {}, "notes": []},
                        }
                    ).encode("utf-8"),
                    mtime=0,
                )
            )

    def test_preserves_hidden_guide_without_counting_it_as_judgement(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {
                            "type": "guide",
                            "node": [
                                {
                                    "visible": False,
                                    "t": 480,
                                    "pos": 12,
                                    "size": 8,
                                },
                                {"visible": False, "t": 720, "pos": "auto"},
                                {
                                    "visible": False,
                                    "t": 960,
                                    "pos": 4,
                                    "size": 8,
                                },
                            ],
                        }
                    ],
                }
            )
        )

        self.assertEqual(chart["notes"][0]["type"], "guide")
        self.assertIsNone(chart["notes"][0]["nodes"][1]["position"])
        self.assertEqual(
            chart["statistics"]["noteCounts"],
            {"tap": 0, "flick": 0, "trace": 0, "long": 0},
        )
        self.assertEqual(chart["statistics"]["judgementCount"], 0)

    def test_keeps_guide_nodes_visual_without_creating_combo_events(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {
                            "type": "guide",
                            "node": [
                                {"visible": False, "t": 0, "pos": 2, "size": 2},
                                {"t": 240, "pos": "auto"},
                                {"visible": False, "t": 480, "pos": 6, "size": 2},
                            ],
                        }
                    ],
                }
            )
        )

        self.assertEqual(chart["statistics"]["sourceJudgementCount"], 0)
        self.assertEqual(chart["comboEvents"], [])

    def test_truncates_client_node_milliseconds_before_slide_end_comparison(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 190}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {
                            "type": "long",
                            "node": [
                                {"t": 24480, "pos": 4, "size": 4},
                                {"t": 25920, "pos": 8, "size": 4},
                            ],
                        }
                    ],
                }
            )
        )

        self.assertEqual(chart["statistics"]["rhythmicCandidateCount"], 5)
        self.assertEqual(
            [event["time"] for event in chart["comboEvents"]],
            [
                16.105263,
                16.263,
                16.421,
                16.579,
                16.737,
                16.894,
                17.052632,
            ],
        )

    def test_preserves_trace_note_and_long_node_operate_types(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {"type": "trace", "t": 240, "pos": 3, "size": 2},
                        {
                            "type": "long",
                            "node": [
                                {"t": 480, "pos": 4, "size": 2},
                                {
                                    "type": "trace",
                                    "t": 720,
                                    "pos": 5,
                                    "size": 2,
                                },
                                {
                                    "type": "flick",
                                    "dir": "left",
                                    "t": 960,
                                    "pos": 6,
                                    "size": 2,
                                },
                            ],
                        },
                    ],
                }
            )
        )

        self.assertEqual(chart["notes"][0]["type"], "trace")
        self.assertEqual(chart["notes"][1]["nodes"][1]["operateType"], "trace")
        self.assertEqual(chart["notes"][1]["nodes"][2]["operateType"], "flick")
        self.assertEqual(chart["notes"][1]["nodes"][2]["direction"], "left")
        self.assertEqual(
            chart["statistics"]["noteCounts"],
            {"tap": 0, "flick": 0, "trace": 1, "long": 1},
        )

    def test_preserves_asymmetric_easing_and_critical_flags(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {"t": 0, "pos": 2, "size": 2, "crit": True},
                        {
                            "type": "long",
                            "node": [
                                {
                                    "t": 240,
                                    "pos": 3,
                                    "size": 2,
                                    "ease": ["out", "linear"],
                                    "crit": True,
                                },
                                {"t": 480, "pos": 5, "size": 4},
                            ],
                        },
                    ],
                }
            )
        )

        self.assertTrue(chart["notes"][0]["critical"])
        node = chart["notes"][1]["nodes"][0]
        self.assertEqual(node["easing"], "out")
        self.assertEqual(node["easingRight"], "linear")
        self.assertTrue(node["critical"])

    def test_compiles_runtime_combo_without_a_master_target(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {
                            "type": "long",
                            "node": [
                                {"t": 0, "pos": 2, "size": 3},
                                {"t": 960, "pos": 4, "size": 3},
                            ],
                        }
                    ],
                }
            )
        )

        statistics = chart["statistics"]
        self.assertEqual(statistics["judgementCount"], 5)
        self.assertEqual(statistics["sourceJudgementCount"], 2)
        self.assertEqual(statistics["generatedJudgementCount"], 3)
        self.assertEqual(
            statistics["judgementCountSource"],
            "client-runtime-reconstruction",
        )
        self.assertEqual(
            statistics["densitySource"],
            "client-reconstructed-combo-timeline",
        )
        self.assertEqual(chart["comboEvents"][-1]["combo"], 5)
        self.assertTrue(
            any(event.get("synthetic") for event in chart["comboEvents"])
        )

    def test_public_compiler_accepts_only_the_raw_payload(self) -> None:
        self.assertEqual(
            list(inspect.signature(compile_music_score).parameters),
            ["payload"],
        )

    def test_emits_stable_combo_events_for_each_visible_judgement(self) -> None:
        chart = parse_score_payload(
            score_payload(
                {
                    "events": {
                        "bpm": [{"t": 0, "bpm": 120}],
                        "sig": [],
                        "skill": [],
                        "fever": [],
                        "call": [],
                    },
                    "notes": [
                        {"t": 480, "pos": 2, "size": 3},
                        {"type": "trace", "t": 480, "pos": 5, "size": 2},
                        {
                            "type": "long",
                            "node": [
                                {"t": 240, "pos": 4, "size": 2},
                                {"visible": False, "t": 360, "pos": 5, "size": 2},
                                {"type": "flick", "t": 720, "pos": 6, "size": 2},
                            ],
                        },
                        {
                            "type": "guide",
                            "node": [
                                {"visible": False, "t": 0, "pos": 0, "size": 2},
                                {"visible": False, "t": 960, "pos": 8, "size": 2},
                            ],
                        },
                    ],
                }
            )
        )

        self.assertEqual(
            [
                (
                    event["time"],
                    event["combo"],
                    event["kind"],
                    event["markerId"],
                )
                for event in chart["comboEvents"]
            ],
            [
                (0.25, 1, "explicit-judgement", "note-2:0"),
                (0.375, 2, "topology-connection", None),
                (0.5, 3, "explicit-judgement", "note-0"),
                (0.5, 4, "explicit-judgement", "note-1"),
                (0.5, 5, "slide-combo", None),
                (0.75, 6, "explicit-judgement", "note-2:2"),
            ],
        )
        self.assertEqual(chart["statistics"]["sourceJudgementCount"], 4)


if __name__ == "__main__":
    unittest.main()
