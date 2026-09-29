from __future__ import annotations

import unittest

from tools.unified_search import UnifiedSearchError, build_unified_search_index


class UnifiedSearchTest(unittest.TestCase):
    def test_builds_all_required_entity_types_with_stable_routes(self) -> None:
        catalog = {
            "bands": [{"id": "band-1", "displayName": "MyGO!!!!!"}],
            "characters": [{
                "id": "character-1",
                "displayName": "高松燈",
                "shortName": "燈",
                "aliases": ["Tomori"],
                "role": "Vocal",
                "bandId": "band-1",
                "catalogStatus": "identified",
            }],
            "memberCards": [{
                "id": "member-card-1",
                "displayName": "春日影",
                "subtitle": "迷路的歌",
                "name": "高松燈",
                "characterId": "character-1",
                "masterId": 1,
                "catalogStatus": "identified",
            }],
            "supportCards": [{
                "id": "support-card-1",
                "displayName": "支援卡",
                "description": "大家的舞台",
                "featuredCharacterIds": ["character-1"],
                "masterId": 2,
                "catalogStatus": "identified",
            }],
            "musicTracks": [{
                "id": "music-1",
                "title": "迷星叫",
                "phoneticTitle": "まよいうた",
                "bandLabels": ["MyGO!!!!!"],
                "vocalistLabels": ["高松燈"],
                "lyricist": "作者",
                "composer": "作曲",
                "arranger": "编曲",
                "catalogStatus": "identified",
            }],
        }
        story_search = {
            "entries": [{
                "id": "story-entry-main-1",
                "kind": "main",
                "title": "第一话",
                "summary": "故事摘要",
                "searchableText": "第一话 故事摘要",
                "parseStatus": "metadata_only",
            }]
        }

        result = build_unified_search_index(
            catalog,
            story_search,
            "test-release",
        )

        self.assertEqual(result["sourceReleaseId"], "test-release")
        self.assertEqual(
            {entry["type"] for entry in result["entries"]},
            {"music", "character", "member_card", "support_card", "story"},
        )
        self.assertEqual(
            next(entry for entry in result["entries"] if entry["type"] == "story")["href"],
            "/stories/episodes/story-entry-main-1/",
        )
        member = next(
            entry for entry in result["entries"] if entry["type"] == "member_card"
        )
        self.assertIn("MyGO!!!!!", member["searchableText"])
        self.assertIn("Tomori", member["searchableText"])

    def test_rejects_duplicate_type_and_entity_id(self) -> None:
        catalog = {
            "bands": [],
            "characters": [],
            "memberCards": [],
            "supportCards": [],
            "musicTracks": [
                {"id": "music-1", "title": "A"},
                {"id": "music-1", "title": "B"},
            ],
        }
        with self.assertRaisesRegex(UnifiedSearchError, "duplicate search entry"):
            build_unified_search_index(catalog, {"entries": []}, "test-release")


if __name__ == "__main__":
    unittest.main()
