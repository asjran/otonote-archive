from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.character_media import (
    _audio_index,
    _dedupe_publications,
    build_character_media,
)
from tools.master_catalog import load_master_data
from tools.media_capabilities import merge_media_capabilities


TABLES = (
    "MasterText",
    "MasterBand",
    "MasterCharacter",
    "MasterMemberCard",
    "MasterSupportCard",
    "MasterCharacterCostume",
    "MasterCharacterVoice",
    "MasterTalk",
    "MasterCharacterFriendship",
    "MasterCharacterFriendshipRank",
    "MasterStoryFriendshipEpisode",
    "MasterLiveDialogueCommon",
    "MasterLiveDialogueFixedPair",
    "MasterLiveStartCharacterVoice",
    "MasterLiveGekisouVoice",
    "MasterLoadingComics",
    "MasterStamp",
    "MasterSound",
    "MasterSoundCueSheet",
)


def write_tables(
    root: Path,
    values: dict[str, list[dict[str, object]]],
) -> None:
    for name in TABLES:
        (root / f"{name}.json").write_text(
            json.dumps(
                {"_allData": values.get(name, [])},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


class CharacterMediaTest(unittest.TestCase):
    def test_deduplicates_identical_content_from_different_source_paths(
        self,
    ) -> None:
        publications = _dedupe_publications([
            {
                "id": "character-texture-deadbeef",
                "source": "/export/model-a/texture.png",
                "publicUrl": (
                    "/media/character-textures/"
                    "character-texture-deadbeef.png"
                ),
                "sha256": "deadbeef",
            },
            {
                "id": "character-texture-deadbeef",
                "source": "/export/model-b/texture.png",
                "publicUrl": (
                    "/media/character-textures/"
                    "character-texture-deadbeef.png"
                ),
                "sha256": "deadbeef",
            },
        ])

        self.assertEqual(len(publications), 1)
        self.assertEqual(
            publications[0]["source"],
            "/export/model-a/texture.png",
        )

    def test_audio_index_skips_failed_and_silent_quality_results(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "phone_dump/decrypted_media/export_v2"
            audio_root = report_root / "audio/voicesystem_01_hash"
            audio_root.mkdir(parents=True)
            audible = audio_root / "001_Audible.flac"
            silent = audio_root / "002_Silent.flac"
            suspicious = audio_root / "003_Suspicious.flac"
            for path in (audible, silent, suspicious):
                path.write_bytes(b"audio")
            report = report_root / "cri-media-report.json"
            report.write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "kind": "audio_acb",
                                "source": (
                                    "phone_dump/device/voicesystem_01_"
                                    "0123456789abcdef0123456789abcdef"
                                ),
                                "streams": [
                                    {
                                        "name": "Audible",
                                        "output": str(audible.relative_to(root)),
                                        "validation": {
                                            "ok": True,
                                            "quality": {
                                                "status": "audible",
                                                "ok": True,
                                            },
                                        },
                                    },
                                    {
                                        "name": "Silent",
                                        "output": str(silent.relative_to(root)),
                                        "validation": {
                                            "ok": True,
                                            "quality": {
                                                "status": "silent",
                                                "ok": True,
                                            },
                                        },
                                    },
                                    {
                                        "name": "Suspicious",
                                        "output": str(
                                            suspicious.relative_to(root)
                                        ),
                                        "validation": {
                                            "ok": False,
                                            "quality": {
                                                "status": (
                                                    "suspicious_decryption"
                                                ),
                                                "ok": False,
                                            },
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            index, warnings = _audio_index(report)

            self.assertEqual(
                list(index),
                [("voicesystem_01", "audible")],
            )
            self.assertIn(
                "silent decoded audio skipped: voicesystem_01 / Silent",
                warnings,
            )

    def test_resolves_report_audio_paths_relative_to_repository_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "phone_dump/decrypted_media/export_v2"
            audio_root = report_root / "audio/voicesystem_01_hash"
            audio_root.mkdir(parents=True)
            voice = audio_root / "001_Growth_Tomori_LevelUP_01.flac"
            voice.write_bytes(b"voice")
            report = report_root / "cri-media-report.json"
            report.write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "kind": "audio_acb",
                                "source": (
                                    "phone_dump/device/voicesystem_01_"
                                    "0123456789abcdef0123456789abcdef"
                                ),
                                "streams": [
                                    {
                                        "name": "Growth_Tomori_LevelUP_01",
                                        "output": str(voice.relative_to(root)),
                                        "duration_seconds": 2.5,
                                        "size": 5,
                                        "validation": {
                                            "ok": True,
                                            "quality": {
                                                "status": "audible",
                                                "ok": True,
                                            },
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            index, warnings = _audio_index(report)

            self.assertEqual(warnings, [])
            match = index[
                ("voicesystem_01", "growth_tomori_levelup_01")
            ][0]
            self.assertEqual(Path(match["source"]).resolve(), voice.resolve())

    def test_builds_character_media_with_evidence_based_capabilities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterText": [
                        {"_id": "Character_Name_1", "_japanese": "灯"},
                        {"_id": "CharacterVoice_1", "_japanese": "成长了。"},
                        {"_id": "Talk_Text_1", "_japanese": "今天也要练习。"},
                        {"_id": "Stamp_Name_1", "_japanese": "加油"},
                    ],
                    "MasterBand": [{"_id": 1, "_nameTextID": ""}],
                    "MasterCharacter": [
                        {
                            "_id": 1,
                            "_nameTextID": "Character_Name_1",
                            "_bandID": 1,
                        },
                        {
                            "_id": 2,
                            "_nameTextID": "",
                            "_bandID": 1,
                        },
                    ],
                    "MasterCharacterCostume": [
                        {
                            "_id": 1001,
                            "_characterID": 1,
                            "_costumeID": 1,
                            "_isDefault": True,
                            "_live2dPath": (
                                "001_adv/adv_live2d_tomori_001_live_01/"
                                "model/adv_live2d_tomori_001_live_01"
                            ),
                        },
                        {
                            "_id": 1002,
                            "_characterID": 1,
                            "_costumeID": 2,
                            "_isDefault": False,
                            "_live2dPath": (
                                "001_adv/adv_live2d_tomori_001_missing/"
                                "model/adv_live2d_tomori_001_missing"
                            ),
                        }
                    ],
                    "MasterCharacterVoice": [
                        {
                            "_id": 1,
                            "_characterId": 1,
                            "_type": 0,
                            "_textId": "CharacterVoice_1",
                            "_soundId": 3200101000022,
                            "_scoreRank": 0,
                            "_startAt": "2026/01/01 0:00:00",
                        }
                    ],
                    "MasterTalk": [
                        {
                            "_id": 1,
                            "_characterId": 1,
                            "_costumeId": 0,
                            "_category": 0,
                            "_textId": "Talk_Text_1",
                            "_voiceSoundId": 3200101000002,
                            "_motionName": "mtn_check01_C",
                            "_expressionName": "exp_smile01",
                            "_year": 0,
                            "_seasonStartAt": "",
                            "_seasonEndAt": "",
                            "_birthdayCharacterId": 0,
                            "_unlockCharacterRank": 1,
                        }
                    ],
                    "MasterCharacterFriendship": [
                        {
                            "_id": 102,
                            "_masterCharacterIdA": 1,
                            "_masterCharacterIdB": 2,
                            "_storyBanner": "ui_banner_storyfriend_102",
                        }
                    ],
                    "MasterCharacterFriendshipRank": [
                        {"_id": 1, "_rank": 1, "_exp": 0}
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
                            "_thumbnail": "TBD",
                        }
                    ],
                    "MasterLiveDialogueFixedPair": [
                        {
                            "_id": 1,
                            "_dialogueType": 1,
                            "_characterID01": 1,
                            "_character01ComboVoiceTextID": "Talk_Text_1",
                            "_character01ComboVoiceSoundID": 3200101000002,
                            "_characterID02": 2,
                            "_character02ComboVoiceTextID": "Talk_Text_1",
                            "_character02ComboVoiceSoundID": 3200101000002,
                            "_unlockFriendshipRank": 0,
                        }
                    ],
                    "MasterLoadingComics": [
                        {
                            "_id": 1,
                            "_isDefaultComics": True,
                            "_characterIds": [1],
                            "_imageAsset": "comic_001_1",
                            "_order": 1,
                            "_startAt": "",
                            "_endAt": "",
                        }
                    ],
                    "MasterStamp": [
                        {
                            "_id": 1,
                            "_nameTextId": "Stamp_Name_1",
                            "_stampCategory": 1,
                            "_priority": 1,
                            "_characterIds": [1],
                            "_isInitialOwnership": True,
                            "_stampAsset": (
                                "Stamp/illust/stamp_illust_tomori_001"
                            ),
                            "_voiceAsset": "",
                            "_startAt": "",
                            "_endAt": "",
                        }
                    ],
                    "MasterSound": [
                        {
                            "_id": 3200101000022,
                            "_category": 1,
                            "_soundCueSheetID": 10,
                            "_cueName": "Growth_Tomori_LevelUP_01",
                        },
                        {
                            "_id": 3200101000002,
                            "_category": 1,
                            "_soundCueSheetID": 10,
                            "_cueName": "BandTop_Tomori_Common_01",
                        },
                    ],
                    "MasterSoundCueSheet": [
                        {"_id": 10, "_cueSheetName": "VoiceSystem_01"}
                    ],
                },
            )
            manifest = root / "manifest.json"
            live2d_sprite = root / "sprites/live2d.png"
            live2d_sprite.parent.mkdir(parents=True)
            live2d_sprite.write_bytes(b"live2d-texture")
            (root / "sprites/live2d-01.png").write_bytes(b"live2d-texture-01")
            (root / "sprites/unassigned.png").write_bytes(b"unassigned-texture")
            manifest.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "type": "Texture2D",
                                "name": "comic_001_1",
                                "container_path": (
                                    "Assets/AddressableResources/Image/Comic/"
                                    "comic_001_1.png"
                                ),
                                "exported_file": "textures/comic.png",
                                "bundle": "comic-bundle",
                                "path_id": "1",
                            },
                            {
                                "type": "Sprite",
                                "name": "texture_00",
                                "container_path": (
                                    "Assets/AddressableResources/Character/"
                                    "Live2D/001_adv/"
                                    "adv_live2d_tomori_001_live_01/model/"
                                    "adv_live2d_tomori_001_live_01.2048/"
                                    "texture_00.png"
                                ),
                                "exported_file": "sprites/live2d.png",
                                "bundle": "live2d-bundle",
                                "path_id": "2",
                            },
                            {
                                "type": "Sprite",
                                "name": "texture_01",
                                "container_path": (
                                    "Assets/AddressableResources/Character/"
                                    "Live2D/001_adv/"
                                    "adv_live2d_tomori_001_live_01/model/"
                                    "adv_live2d_tomori_001_live_01.2048/"
                                    "texture_01.png"
                                ),
                                "exported_file": "sprites/live2d-01.png",
                                "bundle": "live2d-bundle",
                                "path_id": "3",
                            },
                            {
                                "type": "Sprite",
                                "name": "texture_orphan",
                                "container_path": (
                                    "Assets/AddressableResources/Character/"
                                    "Live2D/unlinked/model/unlinked.2048/"
                                    "texture_00.png"
                                ),
                                "exported_file": "sprites/unassigned.png",
                                "bundle": "orphan-live2d-bundle",
                                "path_id": "4",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cri_report = root / "cri-media-report.json"
            decoded = root / "decoded"
            decoded.mkdir()
            voice_file = decoded / "voice.flac"
            talk_file = decoded / "talk.flac"
            voice_file.write_bytes(b"voice")
            talk_file.write_bytes(b"talk")
            cri_report.write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "kind": "audio_acb",
                                "source": (
                                    "/input/voicesystem_01_"
                                    "0123456789abcdef0123456789abcdef"
                                ),
                                "streams": [
                                    {
                                        "name": "Growth_Tomori_LevelUP_01",
                                        "output": str(voice_file),
                                        "duration_seconds": 2.5,
                                        "size": 1234,
                                        "validation": {
                                            "ok": True,
                                            "quality": {
                                                "status": "audible",
                                                "ok": True,
                                            },
                                        },
                                    },
                                    {
                                        "name": "BandTop_Tomori_Common_01",
                                        "output": str(talk_file),
                                        "duration_seconds": 3.0,
                                        "size": 2345,
                                        "validation": {
                                            "ok": True,
                                            "quality": {
                                                "status": "audible",
                                                "ok": True,
                                            },
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            master = load_master_data(root)
            story_database = {
                "entries": [
                    {
                        "id": "story-entry-friendship-1",
                        "kind": "friendship",
                        "characterFriendshipId": "character-friendship-102",
                    }
                ]
            }
            catalog_assets = [
                {
                    "id": "asset-comic-1",
                    "containerPath": (
                        "Assets/AddressableResources/Image/Comic/"
                        "comic_001_1.png"
                    ),
                    "previewUrl": "/media/previews/asset-comic-1.webp",
                    "originalUrl": "/media/originals/asset-comic-1.png",
                },
                {
                    "id": "asset-stamp-1",
                    "containerPath": (
                        "Assets/AddressableResources/Stamp/illust/"
                        "stamp_illust_tomori_001.png"
                    ),
                    "previewUrl": "/media/previews/asset-stamp-1.webp",
                    "originalUrl": "/media/originals/asset-stamp-1.png",
                    "sourceBundle": "supplemental-stamp-bundle",
                    "sourceObjectId": "20",
                },
                {
                    "id": "asset-character-portrait-1",
                    "containerPath": (
                        "Assets/AddressableResources/Character/Image/1/"
                        "character_sprite.png"
                    ),
                    "previewUrl": "/media/previews/asset-character-portrait-1.webp",
                    "originalUrl": "/media/originals/asset-character-portrait-1.png",
                },
                {
                    "id": "asset-character-thumbnail-1",
                    "containerPath": (
                        "Assets/AddressableResources/Character/Image/1/"
                        "character_thumbnail.png"
                    ),
                    "previewUrl": "/media/previews/asset-character-thumbnail-1.webp",
                    "originalUrl": "/media/originals/asset-character-thumbnail-1.png",
                }
            ]

            built = build_character_media(
                root,
                master,
                manifest,
                cri_report,
                catalog_assets,
                story_database,
                release_id="test-release",
                audio_playback=True,
                live2d_runtime_report={
                    "evidence": {
                        "sample": {
                            "sourceReleaseId": "test-release",
                            "modelPath": (
                                "001_adv/adv_live2d_tomori_001_live_01/"
                                "model/adv_live2d_tomori_001_live_01"
                            ),
                        }
                    },
                    "decision": {
                        "conclusion": "blocked",
                        "dynamicPlayback": False,
                    },
                    "capabilityUpdate": {
                        "state": "unsupported",
                        "evidencePath": (
                            "analysis/"
                            "live2d-representative-spike-report.json"
                        ),
                    },
                },
            )

            self.assertEqual(len(built.database["costumes"]), 2)
            self.assertEqual(
                built.database["costumes"][0]["modelState"],
                "unsupported",
            )
            costume = built.database["costumes"][0]
            self.assertEqual(costume["runtimeDecision"], "blocked")
            self.assertFalse(costume["dynamicPlayback"])
            self.assertTrue(costume["representativeRuntimeSample"])
            self.assertEqual(costume["textureState"], "available")
            self.assertEqual(costume["textureCount"], 2)
            self.assertEqual(costume["previewState"], "metadata_only")
            self.assertEqual(len(costume["textureCandidates"]), 2)
            self.assertTrue(
                costume["textureCandidates"][0]["previewUrl"].startswith(
                    "/media/character-textures/"
                )
            )
            self.assertEqual(
                built.database["costumes"][1]["textureState"],
                "metadata_only",
            )
            self.assertFalse(
                built.database["costumes"][1][
                    "representativeRuntimeSample"
                ]
            )
            self.assertEqual(
                [item["name"] for item in built.database[
                    "unassignedTextureCandidates"
                ]],
                ["texture_orphan"],
            )
            voice = built.database["voices"][0]
            self.assertEqual(voice["capabilityState"], "available")
            self.assertEqual(voice["cueSheetName"], "VoiceSystem_01")
            self.assertTrue(voice["audioUrl"].startswith("/media/audio/"))
            self.assertEqual(
                built.database["talks"][0]["capabilityState"],
                "available",
            )
            friendship = built.database["friendships"][0]
            self.assertEqual(
                friendship["characterIds"],
                ["character-1", "character-2"],
            )
            self.assertEqual(
                friendship["storyEntryIds"],
                ["story-entry-friendship-1"],
            )
            media_by_kind = {
                item["kind"]: item
                for item in built.database["mediaItems"]
            }
            self.assertEqual(
                media_by_kind["comic"]["assetId"],
                "asset-comic-1",
            )
            self.assertEqual(
                media_by_kind["stamp"]["capabilityState"],
                "available",
            )
            self.assertEqual(
                media_by_kind["stamp"]["previewUrl"],
                "/media/previews/asset-stamp-1.webp",
            )
            portrait_items = [
                item for item in built.database["mediaItems"]
                if item["kind"] == "portrait"
            ]
            self.assertEqual(
                [item["assetId"] for item in portrait_items],
                ["asset-character-portrait-1", "asset-character-thumbnail-1"],
            )
            projection = built.projections["characters"][0]
            self.assertEqual(
                projection["counts"],
                {
                    "costumes": 2,
                    "voices": 1,
                    "talks": 1,
                    "friendships": 1,
                    "media": 4,
                },
            )
            self.assertEqual(len(built.audio_publications), 2)
            self.assertEqual(len(built.texture_publications), 3)
            live2d_capability = next(
                item for item in built.capabilities
                if item["role"] == "live2d_model"
                and item["owner"]["id"] == costume["id"]
            )
            self.assertEqual(
                live2d_capability["runtimeDecision"],
                "blocked",
            )
            self.assertFalse(live2d_capability["dynamicPlayback"])

    def test_merges_story_and_character_capabilities_once(self) -> None:
        story = {
            "schemaVersion": 1,
            "sourceReleaseId": "test-release",
            "capabilities": [
                {
                    "id": "media-story",
                    "state": "available",
                    "role": "chapter_banner",
                }
            ],
            "byReference": {"chapter:1:banner": "media-story"},
        }
        character = [
            {
                "id": "media-character",
                "state": "metadata_only",
                "role": "character_voice_audio",
            }
        ]

        merged = merge_media_capabilities(
            story,
            character,
            release_id="test-release",
        )

        self.assertEqual(
            [item["id"] for item in merged["capabilities"]],
            ["media-character", "media-story"],
        )
        self.assertEqual(
            merged["byReference"]["chapter:1:banner"],
            "media-story",
        )


if __name__ == "__main__":
    unittest.main()
