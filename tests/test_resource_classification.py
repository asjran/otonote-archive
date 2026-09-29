from __future__ import annotations

import unittest

from tools.resource_classification import classify_resource


class ResourceClassificationTest(unittest.TestCase):
    def test_identifies_assets_with_verified_entity_relations(self) -> None:
        result = classify_resource(
            "skill",
            "Assets/AddressableResources/Skill/Icon/skill_001.png",
        )

        self.assertEqual(result["catalogStatus"], "identified")
        self.assertEqual(result["publicPolicy"], "public")
        self.assertEqual(result["classificationEvidence"], "entity_kind")

    def test_archives_story_artwork_without_guessing_an_entity_relation(self) -> None:
        result = classify_resource(
            "banner",
            "Assets/AddressableResources/Story/Banner/Episode/banner.png",
        )

        self.assertEqual(result["catalogStatus"], "archive_only")
        self.assertEqual(result["publicPolicy"], "archive_only")
        self.assertEqual(result["classificationReason"], "story_artwork")

    def test_hides_source_placeholders(self) -> None:
        result = classify_resource(
            "cover",
            "Assets/AddressableResources/Image/Jacket/small/tentative_cover_11.png",
        )

        self.assertEqual(result["catalogStatus"], "source_placeholder")
        self.assertEqual(result["publicPolicy"], "not_public")

    def test_keeps_unknown_paths_pending(self) -> None:
        result = classify_resource("other", "Unknown/New/Path.png")

        self.assertEqual(result["catalogStatus"], "pending")
        self.assertEqual(result["publicPolicy"], "review_required")


if __name__ == "__main__":
    unittest.main()
