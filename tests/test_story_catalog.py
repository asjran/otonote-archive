from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.adv_adapter import build_adv_database, parse_adv
from tools.media_capabilities import build_media_capabilities
from tools.story_catalog import (
    StoryCatalogError,
    build_story_catalog,
)
from tools.story_pipeline import build_story_pipeline


STORY_TABLES = (
    "MasterStoryChapter",
    "MasterStoryEpisode",
    "MasterStoryFriendshipEpisode",
    "MasterStoryHomeSpotTapTalkEpisode",
    "MasterStoryLiveResultEpisode",
    "MasterAdv",
    "MasterAdvChat",
    "MasterAdvPlayTime",
    "MasterHomeSpot",
    "MasterStoryReward",
    "MasterCharacterFriendship",
    "MasterText",
    "MasterCharacter",
    "MasterBand",
    "MasterMemberCard",
    "MasterSupportCard",
)


def write_tables(root: Path, values: dict[str, list[dict[str, object]]]) -> None:
    for name in STORY_TABLES:
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": values.get(name, [])}, ensure_ascii=False),
            encoding="utf-8",
        )


def base_master() -> dict[str, list[dict[str, object]]]:
    return {
        "MasterText": [],
        "MasterBand": [],
        "MasterCharacter": [],
        "MasterCharacterFriendship": [],
        "MasterHomeSpot": [],
        "MasterStoryChapter": [],
        "MasterStoryEpisode": [],
        "MasterStoryFriendshipEpisode": [],
        "MasterStoryHomeSpotTapTalkEpisode": [],
        "MasterStoryLiveResultEpisode": [],
        "MasterAdv": [],
        "MasterAdvChat": [],
        "MasterAdvPlayTime": [],
        "MasterStoryReward": [],
    }


def write_manifest(root: Path, assets: list[dict[str, object]]) -> Path:
    extracted = root / "device_resources_extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    (extracted / "manifest.json").write_text(
        json.dumps({"assets": assets}, ensure_ascii=False),
        encoding="utf-8",
    )
    return extracted


class StoryCatalogTest(unittest.TestCase):
    def _master(self) -> dict[str, list[dict[str, object]]]:
        return {
            "MasterText": [
                {"_id": "Story_Chapter_Name_1", "_japanese": "第一章"},
                {"_id": "Story_Chapter_Description_1", "_japanese": "简介"},
                {"_id": "Story_Episode_Description_1", "_japanese": "集简介"},
                {"_id": "Chapter_Title_1", "_japanese": "第一章第一集"},
                {"_id": "Chapter_Title_2", "_japanese": "第一章第二集"}
            ],
            "MasterBand": [{"_id": 1, "_nameTextID": ""}],
            "MasterCharacter": [{"_id": 1, "_nameTextID": "", "_bandID": 1}],
            "MasterCharacterFriendship": [
                {"_id": 102, "_characterID": 1}
            ],
            "MasterHomeSpot": [
                {
                    "_id": 10007,
                    "_bandId": 1,
                    "_characterIds": [1],
                    "_advNameTextId": "",
                    "_advId": 0,
                    "_backgroundAssetPath": "",
                    "_situationAssetPath": ""
                }
            ],
            "MasterStoryChapter": [
                {
                    "_id": 1,
                    "_nameTextId": "Story_Chapter_Name_1",
                    "_descriptionTextId": "Story_Chapter_Description_1",
                    "_bandId": 1,
                    "_isSpecialStory": False,
                    "_mainCharacterIds": [1],
                    "_musicId": 100002,
                    "_eventId": 0,
                    "_startAt": "",
                    "_endAt": "",
                    "_banner": "ui_banner_chapter_1",
                    "_image": "ui_image_chapter_1",
                    "_icon": "ui_icon_chapter_1"
                }
            ],
            "MasterStoryEpisode": [
                {
                    "_id": 1,
                    "_chapterId": 1,
                    "_episodeNumber": 1,
                    "_descriptionTextId": "Story_Episode_Description_1",
                    "_advId": 10000,
                    "_characterId": 0,
                    "_isAnotherEpisode": False,
                    "_isExtraEpisode": False,
                    "_unlockEpisodeNumber": 0,
                    "_eventPoint": 0,
                    "_characterRank": 0,
                    "_storyFriendshipEpisodeId": 0,
                    "_storyRewardGroupId": 1,
                    "_eventStoryRewardGroupId": 0,
                    "_isEventSecondHalfEpisode": False,
                    "_banner": "ui_banner_chapter_1_episode_1",
                    "_image": "ui_image_chapter_1_episode_1",
                    "_thumbnail": "TBD"
                },
                {
                    "_id": 2,
                    "_chapterId": 1,
                    "_episodeNumber": 2,
                    "_descriptionTextId": "",
                    "_advId": 10001,
                    "_characterId": 0,
                    "_isAnotherEpisode": False,
                    "_isExtraEpisode": False,
                    "_unlockEpisodeNumber": 0,
                    "_eventPoint": 0,
                    "_characterRank": 0,
                    "_storyFriendshipEpisodeId": 0,
                    "_storyRewardGroupId": 1,
                    "_eventStoryRewardGroupId": 0,
                    "_isEventSecondHalfEpisode": False,
                    "_banner": "ui_banner_chapter_1_episode_2",
                    "_image": "ui_image_chapter_1_episode_2",
                    "_thumbnail": "TBD"
                }
            ],
            "MasterStoryFriendshipEpisode": [
                {
                    "_id": 1,
                    "_characterFriendshipId": 102,
                    "_episodeNumber": 1,
                    "_advId": 10459,
                    "_unlockCharacterFriendshipLevel": 1,
                    "_storyRewardGroupId": 3,
                    "_banner": "ui_banner_storyfriend_102_episode_1",
                    "_thumbnail": "TBD"
                }
            ],
            "MasterStoryHomeSpotTapTalkEpisode": [
                {"_id": 1, "_spotId": 10007, "_characterId": 1, "_advId": 10667}
            ],
            "MasterStoryLiveResultEpisode": [
                {
                    "_id": 1,
                    "_characterIds": [1],
                    "_unlockCharacterFriendshipLevel": 0,
                    "_advId": 10109
                }
            ],
            "MasterAdv": [
                {
                    "_id": 10000,
                    "_sheetName": "adv_script_chapter_001_1_01",
                    "_advEpisodeAsset": "adv_script_chapter_001_1_01",
                    "_titleTextId": "Chapter_Title_1",
                    "_playbackMode": 0
                },
                {
                    "_id": 10001,
                    "_sheetName": "adv_script_chapter_001_1_02",
                    "_advEpisodeAsset": "adv_script_chapter_001_1_02",
                    "_titleTextId": "Chapter_Title_2",
                    "_playbackMode": 0
                },
                {
                    "_id": 10459,
                    "_sheetName": "adv_script_storyfriend_102_episode_1",
                    "_advEpisodeAsset": "adv_script_storyfriend_102_episode_1",
                    "_titleTextId": "",
                    "_playbackMode": 0
                },
                {
                    "_id": 10667,
                    "_sheetName": "adv_script_homespot_10007_1",
                    "_advEpisodeAsset": "adv_script_homespot_10007_1",
                    "_titleTextId": "",
                    "_playbackMode": 1
                },
                {
                    "_id": 10109,
                    "_sheetName": "adv_script_afterlive_10109",
                    "_advEpisodeAsset": "adv_script_afterlive_10109",
                    "_titleTextId": "",
                    "_playbackMode": 1
                }
            ],
            "MasterAdvChat": [],
            "MasterAdvPlayTime": [],
            "MasterStoryReward": [
                {
                    "_id": 1,
                    "_group": 1,
                    "_resourceType": 1,
                    "_resourceId": 1,
                    "_resourceCount": 50
                }
            ],
        }

    def test_normalizes_four_story_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            kinds = {entry["kind"] for entry in build.entries}
            self.assertEqual(
                kinds,
                {"main", "friendship", "home_spot", "live_result"},
            )
            self.assertEqual(len(build.chapters), 1)
            chapter = build.chapters[0]
            self.assertEqual(chapter["episodeIds"], [
                "story-entry-main-1",
                "story-entry-main-2"
            ])
            main_entries = [
                entry for entry in build.entries if entry["kind"] == "main"
            ]
            self.assertEqual(
                [entry["episodeNumber"] for entry in main_entries],
                [1, 2]
            )

    def test_rejects_missing_required_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, base_master())
            (root / "MasterAdv.json").unlink()
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            with self.assertRaises(StoryCatalogError):
                build_story_catalog(root, master)

    def test_rejects_dangling_chapter_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tables = self._master()
            tables["MasterStoryEpisode"][0]["_chapterId"] = 99
            write_tables(root, tables)
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            with self.assertRaises(StoryCatalogError):
                build_story_catalog(root, master)

    def test_adv_metadata_resolves_for_each_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            for entry in build.entries:
                self.assertIsNotNone(entry["adv"], entry["id"])
                self.assertGreater(entry["adv"]["masterId"], 0)

    def test_treats_tbd_thumbnail_as_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            main_entries = [
                entry for entry in build.entries if entry["kind"] == "main"
            ]
            self.assertTrue(
                all(entry["thumbnailIsPlaceholder"] for entry in main_entries)
            )
            self.assertTrue(
                all(not entry["thumbnailAssetName"] for entry in main_entries)
            )


class MediaCapabilitiesTest(unittest.TestCase):
    def _master(self) -> dict[str, list[dict[str, object]]]:
        return {
            "MasterText": [
                {"_id": "Story_Chapter_Name_1", "_japanese": "第一章"},
                {"_id": "Story_Chapter_Description_1", "_japanese": "简介"},
                {"_id": "Chapter_Title_1", "_japanese": "第一章第一集"}
            ],
            "MasterBand": [{"_id": 1, "_nameTextID": ""}],
            "MasterCharacter": [{"_id": 1, "_nameTextID": "", "_bandID": 1}],
            "MasterCharacterFriendship": [
                {"_id": 102, "_characterID": 1}
            ],
            "MasterHomeSpot": [
                {
                    "_id": 10007,
                    "_bandId": 1,
                    "_characterIds": [1],
                    "_advNameTextId": "",
                    "_advId": 0,
                    "_backgroundAssetPath": "",
                    "_situationAssetPath": ""
                }
            ],
            "MasterStoryChapter": [
                {
                    "_id": 1,
                    "_nameTextId": "Story_Chapter_Name_1",
                    "_descriptionTextId": "Story_Chapter_Description_1",
                    "_bandId": 1,
                    "_isSpecialStory": False,
                    "_mainCharacterIds": [1],
                    "_musicId": 100002,
                    "_eventId": 0,
                    "_startAt": "",
                    "_endAt": "",
                    "_banner": "ui_banner_chapter_1",
                    "_image": "ui_image_chapter_1",
                    "_icon": "ui_icon_chapter_1"
                }
            ],
            "MasterStoryEpisode": [
                {
                    "_id": 1,
                    "_chapterId": 1,
                    "_episodeNumber": 1,
                    "_descriptionTextId": "Story_Episode_Description_1",
                    "_advId": 10000,
                    "_characterId": 0,
                    "_isAnotherEpisode": False,
                    "_isExtraEpisode": False,
                    "_unlockEpisodeNumber": 0,
                    "_eventPoint": 0,
                    "_characterRank": 0,
                    "_storyFriendshipEpisodeId": 0,
                    "_storyRewardGroupId": 1,
                    "_eventStoryRewardGroupId": 0,
                    "_isEventSecondHalfEpisode": False,
                    "_banner": "ui_banner_chapter_1_episode_1",
                    "_image": "ui_image_chapter_1_episode_1",
                    "_thumbnail": "TBD"
                }
            ],
            "MasterStoryFriendshipEpisode": [],
            "MasterStoryHomeSpotTapTalkEpisode": [],
            "MasterStoryLiveResultEpisode": [],
            "MasterAdv": [
                {
                    "_id": 10000,
                    "_sheetName": "adv_script_chapter_001_1_01",
                    "_advEpisodeAsset": "adv_script_chapter_001_1_01",
                    "_titleTextId": "Chapter_Title_1",
                    "_playbackMode": 0
                }
            ],
            "MasterAdvChat": [],
            "MasterAdvPlayTime": [],
            "MasterStoryReward": [],
        }

    def test_resolves_available_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            extracted = write_manifest(
                root,
                [
                    {
                        "bundle": "b1",
                        "path_id": 1,
                        "type": "Texture2D",
                        "name": "ui_banner_chapter_1",
                        "container_path": (
                            "Assets/AddressableResources/Story/Banner/"
                            "Chapter/ui_banner_chapter_1.png"
                        ),
                        "exported_file": "textures/chapter_1.png",
                    }
                ],
            )
            capabilities = build_media_capabilities(
                root / "device_resources_extracted/manifest.json",
                story_chapters=build.chapters,
                story_entries=build.entries,
            )
            chapter_banner = next(
                cap for cap in capabilities.capabilities
                if cap["role"] == "chapter_banner"
            )
            self.assertEqual(chapter_banner["state"], "available")
            self.assertIn(
                "Assets/AddressableResources/Story/Banner/Chapter",
                chapter_banner["containerPath"] or "",
            )
            self.assertNotIn(
                "ui_banner_storyfriend",
                (chapter_banner["containerPath"] or ""),
            )

    def test_metadata_only_when_no_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            write_manifest(root, [])
            capabilities = build_media_capabilities(
                root / "device_resources_extracted/manifest.json",
                story_chapters=build.chapters,
                story_entries=build.entries,
            )
            states = {cap["state"] for cap in capabilities.capabilities}
            self.assertIn("metadata_only", states)


class AdvAdapterTest(unittest.TestCase):
    def _master(self) -> dict[str, list[dict[str, object]]]:
        return {
            "MasterText": [
                {"_id": "Story_Chapter_Name_1", "_japanese": "第一章"},
                {"_id": "Story_Chapter_Description_1", "_japanese": "简介"},
                {"_id": "Story_Episode_Description_1", "_japanese": "集简介"},
                {"_id": "Chapter_Title_1", "_japanese": "第一章第一集"},
                {"_id": "Chapter_Title_2", "_japanese": "第一章第二集"}
            ],
            "MasterBand": [{"_id": 1, "_nameTextID": ""}],
            "MasterCharacter": [{"_id": 1, "_nameTextID": "", "_bandID": 1}],
            "MasterCharacterFriendship": [
                {"_id": 102, "_characterID": 1}
            ],
            "MasterHomeSpot": [
                {
                    "_id": 10007,
                    "_bandId": 1,
                    "_characterIds": [1],
                    "_advNameTextId": "",
                    "_advId": 0,
                    "_backgroundAssetPath": "",
                    "_situationAssetPath": ""
                }
            ],
            "MasterStoryChapter": [
                {
                    "_id": 1,
                    "_nameTextId": "Story_Chapter_Name_1",
                    "_descriptionTextId": "Story_Chapter_Description_1",
                    "_bandId": 1,
                    "_isSpecialStory": False,
                    "_mainCharacterIds": [1],
                    "_musicId": 100002,
                    "_eventId": 0,
                    "_startAt": "",
                    "_endAt": "",
                    "_banner": "ui_banner_chapter_1",
                    "_image": "ui_image_chapter_1",
                    "_icon": "ui_icon_chapter_1"
                }
            ],
            "MasterStoryEpisode": [
                {
                    "_id": 1,
                    "_chapterId": 1,
                    "_episodeNumber": 1,
                    "_descriptionTextId": "Story_Episode_Description_1",
                    "_advId": 10000,
                    "_characterId": 0,
                    "_isAnotherEpisode": False,
                    "_isExtraEpisode": False,
                    "_unlockEpisodeNumber": 0,
                    "_eventPoint": 0,
                    "_characterRank": 0,
                    "_storyFriendshipEpisodeId": 0,
                    "_storyRewardGroupId": 1,
                    "_eventStoryRewardGroupId": 0,
                    "_isEventSecondHalfEpisode": False,
                    "_banner": "ui_banner_chapter_1_episode_1",
                    "_image": "ui_image_chapter_1_episode_1",
                    "_thumbnail": "TBD"
                }
            ],
            "MasterStoryFriendshipEpisode": [],
            "MasterStoryHomeSpotTapTalkEpisode": [],
            "MasterStoryLiveResultEpisode": [],
            "MasterAdv": [
                {
                    "_id": 10000,
                    "_sheetName": "adv_script_chapter_001_1_01",
                    "_advEpisodeAsset": "adv_script_chapter_001_1_01",
                    "_titleTextId": "Chapter_Title_1",
                    "_playbackMode": 0
                }
            ],
            "MasterAdvChat": [],
            "MasterAdvPlayTime": [],
            "MasterStoryReward": [],
        }

    def test_missing_text_shard_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            build = build_story_catalog(root, master)
            write_manifest(root, [])
            adv = build_adv_database(
                root / "device_resources_extracted/manifest.json",
                root / "device_resources_extracted",
                build.entries,
            )
            self.assertEqual(
                {state["state"] for state in adv.per_adv_status.values()},
                {"metadata_only"},
            )
            for document in adv.documents.values():
                self.assertEqual(document.parse_status, "metadata_only")
                self.assertEqual(document.shard_states["Text"], "missing")

    def test_corrupt_shard_raises_build_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            textassets = root / "device_resources_extracted/textassets"
            textassets.mkdir(parents=True, exist_ok=True)
            (textassets / "tutorial_text.json").write_text(
                "{not json", encoding="utf-8"
            )
            (root / "device_resources_extracted/manifest.json").write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "bundle": "b1",
                                "path_id": 1,
                                "type": "TextAsset",
                                "container_path": (
                                    "Assets/AddressableResources/Adv/Episode/"
                                    "adv_script_tutorial_001/"
                                    "adv_script_tutorial_001-Text.txt"
                                ),
                                "exported_file": (
                                    "textassets/tutorial_text.json"
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(Exception):
                parse_adv(
                    adv_master_id=1,
                    adv_identifier="adv_script_tutorial_001",
                    manifest_index={
                        "Assets/AddressableResources/Adv/Episode/"
                        "adv_script_tutorial_001/"
                        "adv_script_tutorial_001-Text.txt": {
                            "container_path": (
                                "Assets/AddressableResources/Adv/Episode/"
                                "adv_script_tutorial_001/"
                                "adv_script_tutorial_001-Text.txt"
                            ),
                            "exported_file": "textassets/tutorial_text.json",
                        }
                    },
                    extracted_root=root / "device_resources_extracted",
                )

    def test_tutorial_shard_is_unsupported_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            textassets = root / "device_resources_extracted/textassets"
            textassets.mkdir(parents=True, exist_ok=True)
            (textassets / "tutorial_text.json").write_text(
                json.dumps(
                    {
                        "_allData": [
                            {
                                "_id": "adv_script_tutorial_001_1",
                                "_japanese": "サンプル"
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "device_resources_extracted/manifest.json").write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "bundle": "b1",
                                "path_id": 1,
                                "type": "TextAsset",
                                "container_path": (
                                    "Assets/AddressableResources/Adv/Episode/"
                                    "adv_script_tutorial_001/"
                                    "adv_script_tutorial_001-Text.txt"
                                ),
                                "exported_file": (
                                    "textassets/tutorial_text.json"
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            document = parse_adv(
                adv_master_id=1,
                adv_identifier="adv_script_tutorial_001",
                manifest_index={
                    "Assets/AddressableResources/Adv/Episode/"
                    "adv_script_tutorial_001/"
                    "adv_script_tutorial_001-Text.txt": {
                        "container_path": (
                            "Assets/AddressableResources/Adv/Episode/"
                            "adv_script_tutorial_001/"
                            "adv_script_tutorial_001-Text.txt"
                        ),
                        "exported_file": "textassets/tutorial_text.json",
                    }
                },
                extracted_root=root / "device_resources_extracted",
            )
            self.assertEqual(document.parse_status, "unsupported")
            self.assertEqual(document.shard_states["Text"], "available")
            self.assertEqual(len(document.locale_lines), 1)
            self.assertEqual(document.locale_lines[0]["id"], "adv_script_tutorial_001_1")
            self.assertEqual(document.locale_lines[0]["japanese"], "サンプル")


class StoryPipelineTest(unittest.TestCase):
    def _master(self) -> dict[str, list[dict[str, object]]]:
        return {
            "MasterText": [
                {"_id": "Story_Chapter_Name_1", "_japanese": "第一章"},
                {"_id": "Story_Chapter_Description_1", "_japanese": "简介"},
                {"_id": "Story_Episode_Description_1", "_japanese": "集简介"},
                {"_id": "Chapter_Title_1", "_japanese": "第一章第一集"},
                {"_id": "Chapter_Title_2", "_japanese": "第一章第二集"}
            ],
            "MasterBand": [{"_id": 1, "_nameTextID": ""}],
            "MasterCharacter": [{"_id": 1, "_nameTextID": "", "_bandID": 1}],
            "MasterCharacterFriendship": [
                {"_id": 102, "_characterID": 1}
            ],
            "MasterHomeSpot": [
                {
                    "_id": 10007,
                    "_bandId": 1,
                    "_characterIds": [1],
                    "_advNameTextId": "",
                    "_advId": 0,
                    "_backgroundAssetPath": "",
                    "_situationAssetPath": ""
                }
            ],
            "MasterStoryChapter": [
                {
                    "_id": 1,
                    "_nameTextId": "Story_Chapter_Name_1",
                    "_descriptionTextId": "Story_Chapter_Description_1",
                    "_bandId": 1,
                    "_isSpecialStory": False,
                    "_mainCharacterIds": [1],
                    "_musicId": 100002,
                    "_eventId": 0,
                    "_startAt": "",
                    "_endAt": "",
                    "_banner": "ui_banner_chapter_1",
                    "_image": "ui_image_chapter_1",
                    "_icon": "ui_icon_chapter_1"
                }
            ],
            "MasterStoryEpisode": [
                {
                    "_id": 1,
                    "_chapterId": 1,
                    "_episodeNumber": 1,
                    "_descriptionTextId": "Story_Episode_Description_1",
                    "_advId": 10000,
                    "_characterId": 0,
                    "_isAnotherEpisode": False,
                    "_isExtraEpisode": False,
                    "_unlockEpisodeNumber": 0,
                    "_eventPoint": 0,
                    "_characterRank": 0,
                    "_storyFriendshipEpisodeId": 0,
                    "_storyRewardGroupId": 1,
                    "_eventStoryRewardGroupId": 0,
                    "_isEventSecondHalfEpisode": False,
                    "_banner": "ui_banner_chapter_1_episode_1",
                    "_image": "ui_image_chapter_1_episode_1",
                    "_thumbnail": "TBD"
                }
            ],
            "MasterStoryFriendshipEpisode": [],
            "MasterStoryHomeSpotTapTalkEpisode": [],
            "MasterStoryLiveResultEpisode": [],
            "MasterAdv": [
                {
                    "_id": 10000,
                    "_sheetName": "adv_script_chapter_001_1_01",
                    "_advEpisodeAsset": "adv_script_chapter_001_1_01",
                    "_titleTextId": "Chapter_Title_1",
                    "_playbackMode": 0
                }
            ],
            "MasterAdvChat": [],
            "MasterAdvPlayTime": [],
            "MasterStoryReward": [],
        }

    def test_pipeline_emits_all_four_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(root, self._master())
            from tools.master_catalog import load_master_data

            master = load_master_data(root)
            extracted = write_manifest(
                root,
                [
                    {
                        "bundle": "b1",
                        "path_id": 1,
                        "type": "Texture2D",
                        "name": "ui_banner_chapter_1",
                        "container_path": (
                            "Assets/AddressableResources/Story/Banner/"
                            "Chapter/ui_banner_chapter_1.png"
                        ),
                        "exported_file": "textures/chapter_1.png",
                    }
                ],
            )
            pipeline = build_story_pipeline(
                root,
                master,
                root / "device_resources_extracted/manifest.json",
                root / "device_resources_extracted",
                release_id="test-release",
                adv_runtime_report={
                    "evidence": {
                        "sample": {
                            "sourceReleaseId": "test-release",
                            "advMasterId": 10000,
                        },
                        "root": {"found": True, "commandCount": 5},
                        "storyAstCandidate": {
                            "nodeCount": 7,
                            "nodeTypeCounts": {"Dialogue": 1},
                        },
                    },
                    "decision": {
                        "conclusion": "blocked",
                        "readerEnabled": False,
                        "blockers": ["runtime validation missing"],
                        "gates": {"runtimeValidationConfirmed": False},
                    },
                    "capabilityUpdate": {
                        "state": "unsupported",
                        "evidencePath": "analysis/adv-report.json",
                    },
                },
            )
            self.assertEqual(len(pipeline.database["chapters"]), 1)
            self.assertGreater(len(pipeline.database["entries"]), 0)
            self.assertGreater(len(pipeline.media_capabilities["capabilities"]), 0)
            chapter_records = pipeline.search_index["chapters"]
            self.assertEqual(len(chapter_records), 1)
            self.assertEqual(chapter_records[0]["title"], "第一章")
            line_records = pipeline.search_index["lines"]
            self.assertEqual(line_records, [])
            report = pipeline.quality_report
            self.assertEqual(report["chapterCount"], 1)
            self.assertEqual(report["entriesByKind"].get("main"), 1)
            self.assertNotIn("friendship", report["entriesByKind"])
            entry_adv = pipeline.database["entries"][0]["adv"]
            self.assertEqual(entry_adv["parseStatus"], "metadata_only")
            self.assertEqual(entry_adv["runtimeAudit"]["decision"], "blocked")
            self.assertEqual(entry_adv["runtimeAudit"]["storyAstNodeCount"], 7)
            self.assertFalse(entry_adv["runtimeAudit"]["readerEnabled"])
            self.assertEqual(
                pipeline.database["documents"]["adv-10000"]["runtimeAudit"],
                entry_adv["runtimeAudit"],
            )
            self.assertEqual(
                report["representativeAdvAudit"]["advMasterId"],
                10000,
            )


if __name__ == "__main__":
    unittest.main()
