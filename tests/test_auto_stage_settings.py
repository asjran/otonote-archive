from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.auto_stage_settings import build_auto_stage_settings


class AutoStageSettingsTest(unittest.TestCase):
    def test_projects_verified_ranges_defaults_and_note_sounds(self) -> None:
        defaults = {
            "_allData": [
                {"_presetId": 1, "_optionItemType": 1, "_valueString": "5.00"},
                {"_presetId": 1, "_optionItemType": 2, "_valueString": "0.00"},
                {"_presetId": 1, "_optionItemType": 411, "_valueString": "50"},
            ]
        }
        ranges = {
            "_allData": [
                {"_optionItemType": 1, "_minValue": 100, "_maxValue": 1200},
                {"_optionItemType": 2, "_minValue": -300, "_maxValue": 300},
                {"_optionItemType": 411, "_minValue": 0, "_maxValue": 100},
            ]
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "perfect.flac"
            audio.write_bytes(b"audio")
            result = build_auto_stage_settings(
                defaults,
                ranges,
                {
                    "files": [
                        {
                            "kind": "audio_unity_acb",
                            "cue_sheet_name": "default_perfect",
                            "ok": True,
                            "streams": [{"output": str(audio)}],
                        }
                    ]
                },
                public_root=root / "public",
            )

            settings = {item["id"]: item for item in result["gameSettings"]}
            self.assertEqual(settings["noteSpeed"]["default"], 5)
            self.assertEqual(settings["noteSpeed"]["min"], 1)
            self.assertEqual(settings["noteSpeed"]["max"], 12)
            self.assertEqual(settings["noteTimingOffsetMs"]["min"], -300)
            self.assertEqual(settings["noteSeVolume"]["default"], 50)
            self.assertTrue(result["noteSounds"]["tap"]["url"].endswith(".flac"))
            self.assertEqual(result["noteSounds"]["flick"]["state"], "unsupported")

    def test_declares_auto_resource_exclusions(self) -> None:
        with TemporaryDirectory() as temporary:
            result = build_auto_stage_settings(
                {"_allData": []},
                {"_allData": []},
                {"files": []},
                public_root=Path(temporary),
            )

        self.assertEqual(
            result["excludedResourceClasses"],
            ["mv", "vj", "character_voice", "live_voice", "skill_effect"],
        )


if __name__ == "__main__":
    unittest.main()
