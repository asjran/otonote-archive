from __future__ import annotations

import unittest

from tools.story_pipeline import _experimental_runtime_document


class StoryRuntimeReaderTests(unittest.TestCase):
    def test_projects_minimum_readable_flow_and_preserves_unknown_commands(self) -> None:
        report = {
            "evidence": {
                "sample": {"advMasterId": 10109, "sourceReleaseId": "release-1"},
                "root": {"commandCount": 4},
                "localizedText": {
                    "line-1": {"japanese": "本文", "simplifiedChinese": ""},
                    "speaker-1": {"japanese": "燈", "simplifiedChinese": ""},
                },
                "sounds": {
                    "7": {"cueName": "Voice_7", "cueSheetName": "VoiceSheet"},
                },
                "storyAstCandidate": {
                    "nodes": [
                        {
                            "type": "SetCharacterModel",
                            "sourceIndex": 1,
                            "rawCommandId": 23,
                            "characterRef": "tomori",
                            "assetRef": "model/tomori",
                        },
                        {
                            "type": "SetBackground",
                            "sourceIndex": 2,
                            "rawCommandId": 25,
                            "assetRef": "background/stage",
                        },
                        {
                            "type": "Dialogue",
                            "sourceIndex": 3,
                            "rawCommandId": 2,
                            "characterRef": "tomori",
                            "textRef": "line-1",
                            "speakerTextRefs": ["speaker-1"],
                        },
                        {
                            "type": "PlayVoice",
                            "sourceIndex": 3,
                            "rawCommandId": 2,
                            "voiceRef": 7,
                        },
                        {
                            "type": "UnknownCommand",
                            "sourceIndex": 4,
                            "rawCommandId": 99,
                        },
                    ]
                },
            },
            "decision": {
                "conclusion": "experimental",
                "readerEnabled": True,
                "blockers": [],
                "limitations": ["episode dependency missing"],
                "gates": {"commandEnumConfirmed": True},
            },
            "capabilityUpdate": {"state": "experimental"},
        }

        document = _experimental_runtime_document(
            report,
            release_id="release-1",
            adv_master_id=10109,
        )

        self.assertIsNotNone(document)
        assert document is not None
        self.assertEqual(document["parseStatus"], "experimental")
        self.assertEqual(document["lines"][0]["speaker"], "燈")
        self.assertEqual(document["lines"][0]["text"], "本文")
        self.assertEqual(document["lines"][0]["backgroundRef"], "background/stage")
        self.assertEqual(document["lines"][0]["characterAssetRef"], "model/tomori")
        self.assertEqual(document["lines"][0]["audio"]["cueName"], "Voice_7")
        self.assertIsNone(document["lines"][0]["audio"]["url"])
        self.assertEqual(document["unknownCommands"][0]["rawCommandId"], 99)
        self.assertEqual(document["limitations"], ["episode dependency missing"])

    def test_missing_media_does_not_block_resolved_text(self) -> None:
        report = {
            "evidence": {
                "sample": {"advMasterId": 10109, "sourceReleaseId": "release-1"},
                "localizedText": {"line-1": {"japanese": "本文"}},
                "sounds": {},
                "storyAstCandidate": {
                    "nodes": [
                        {
                            "type": "Dialogue",
                            "sourceIndex": 1,
                            "rawCommandId": 2,
                            "textRef": "line-1",
                            "speakerTextRefs": [],
                        }
                    ]
                },
            },
            "decision": {
                "conclusion": "experimental",
                "readerEnabled": True,
                "blockers": [],
                "limitations": [],
                "gates": {"commandEnumConfirmed": True},
            },
            "capabilityUpdate": {"state": "experimental"},
        }

        document = _experimental_runtime_document(
            report,
            release_id="release-1",
            adv_master_id=10109,
        )

        assert document is not None
        self.assertEqual(document["lines"][0]["text"], "本文")
        self.assertIsNone(document["lines"][0]["audio"])


if __name__ == "__main__":
    unittest.main()
