import unittest

from tools.media_capabilities import (
    CAPABILITY_STATES,
    MediaCapabilityError,
    merge_media_capabilities,
)


class MediaCapabilitiesTests(unittest.TestCase):
    def test_merge_rejects_unknown_capability_states(self):
        with self.assertRaisesRegex(
            MediaCapabilityError,
            "unsupported media capability state",
        ):
            merge_media_capabilities(
                {"schemaVersion": 1, "capabilities": [], "byReference": {}},
                [{"id": "invalid-state", "state": "probably"}],
                release_id="global-staging-8135",
            )

    def test_merge_accepts_experimental_capabilities_with_source_evidence(self):
        self.assertIn("experimental", CAPABILITY_STATES)
        merged = merge_media_capabilities(
            {"schemaVersion": 1, "capabilities": [], "byReference": {}},
            [
                {
                    "id": "live2d-character-1001",
                    "state": "experimental",
                    "sourceEvidence": {
                        "snapshotId": "device-8135",
                        "logicalPath": "Assets/Live2D/1001/model.prefab",
                    },
                }
            ],
            release_id="global-staging-8135",
        )

        self.assertEqual(
            merged["capabilities"][0]["state"],
            "experimental",
        )
        self.assertEqual(
            merged["capabilities"][0]["sourceEvidence"]["snapshotId"],
            "device-8135",
        )


if __name__ == "__main__":
    unittest.main()
