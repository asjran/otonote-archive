from __future__ import annotations

import unittest

from tools.live2d_capability import build_capability_report


class Live2DCapabilityTest(unittest.TestCase):
    def test_separates_conversion_browser_motion_and_linked_costume_coverage(self) -> None:
        models = {
            "schemaVersion": 2,
            "models": [
                {
                    "modelId": "a/model/a",
                    "state": "available",
                    "coreBytes": 100,
                    "optionalBytes": 20,
                    "motionState": "supported_motion",
                    "motionPublicationState": "published",
                    "sourceMotionCount": 2,
                    "supportedMotionCount": 1,
                    "blockedMotionCount": 1,
                    "motionCount": 1,
                },
                {
                    "modelId": "b/model/b",
                    "state": "unsupported",
                    "failure": "invalid moc",
                },
            ],
        }
        character_media = {
            "costumes": [
                {"id": "c1", "live2dPath": "a/model/a", "previewState": "available"},
                {"id": "c2", "live2dPath": "b/model/b", "previewState": "available"},
            ]
        }
        browser = {
            "results": [{"modelId": "a/model/a", "state": "passed"}]
        }

        report = build_capability_report(models, character_media, browser)

        self.assertEqual(report["summary"]["candidateCount"], 2)
        self.assertEqual(report["summary"]["linkedCostumeCount"], 2)
        self.assertEqual(report["summary"]["supportedPortraitModelCount"], 1)
        self.assertEqual(report["summary"]["supportedMotionModelCount"], 1)
        self.assertEqual(report["summary"]["sourceMotionCount"], 2)
        self.assertEqual(report["summary"]["convertibleMotionCount"], 1)
        self.assertEqual(report["summary"]["publishedMotionCount"], 1)
        self.assertEqual(report["summary"]["blockedMotionCount"], 1)
        self.assertEqual(report["summary"]["linkedSourceMotionCount"], 2)
        self.assertEqual(report["summary"]["linkedPublishedMotionCount"], 1)
        self.assertEqual(report["summary"]["linkedCostumeClosureCount"], 2)
        self.assertEqual(report["models"][0]["portraitState"], "supported_portrait")
        self.assertEqual(
            report["models"][0]["motionPublicationState"],
            "published",
        )
        self.assertEqual(report["models"][1]["portraitState"], "degraded")


if __name__ == "__main__":
    unittest.main()
