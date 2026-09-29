from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.build_site_catalog import (
    BuildContext,
    CatalogError,
    SiteProjectionArtifacts,
    SiteProjectionBuild,
    SiteProjectionPublications,
    apply_entity_overrides,
    build_catalog,
    classify_kind,
    select_catalog_records,
    stable_id,
    validate_catalog,
    write_release_projection,
)
import tools.build_site_catalog as catalog_builder
from analysis.enrich_unity_manifest_containers import (
    bundle_record_keys,
    enrich_manifest,
)
from tools.master_catalog import parse_resource_identity
from tools.game_database import REQUIRED_TABLES as GAME_DATABASE_TABLES
from tools.story_catalog import REQUIRED_TABLES as STORY_TABLES
from tools.character_media import REQUIRED_TABLES as CHARACTER_MEDIA_TABLES
from tools.band_items import REQUIRED_TABLES as BAND_ITEM_TABLES
from tools.artifact_registry import ArtifactValidationError


class CatalogBuilderTest(unittest.TestCase):
    def test_published_timeline_baseline_uses_previous_matrix_projection(
        self,
    ) -> None:
        self.assertEqual(
            catalog_builder.DEFAULT_PUBLISHED_MUSIC_DATA_ROOT,
            REPO_ROOT
            / "output/release-builds/global-production-current/site/global/zh-CN/data/music-charts",
        )

    def test_release_projection_versions_every_active_site_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = BuildContext(
                content_release_id="jp-test-release",
                region="global",
                channel="staging",
                locale="ja",
                release={},
            )
            build = SiteProjectionBuild(
                catalog={
                    "schemaVersion": 6,
                    "release": {
                        "id": "jp-test-release",
                        "region": "global",
                        "channel": "staging",
                        "locale": "ja",
                    },
                    "projectionContext": {
                        "contentReleaseId": "jp-test-release",
                        "region": "global",
                        "channel": "staging",
                        "locale": "ja",
                    },
                    "bands": [],
                    "characters": [],
                    "memberCards": [],
                    "supportCards": [],
                    "musicTracks": [],
                    "assets": [],
                },
                artifacts=SiteProjectionArtifacts(
                    music_chart_data={},
                    game_database={"name": "game"},
                    game_modes={"name": "modes"},
                    global_systems={"name": "global-systems"},
                    high_score_rating={"name": "rating"},
                    arena_rank={"name": "arena"},
                    unified_search_index={"name": "search"},
                    card_detail_projections={"name": "cards"},
                    band_item_database={"name": "bands"},
                    band_item_quality_report=None,
                    story_database={"name": "stories"},
                    story_search_index={"name": "story-search"},
                    media_capabilities={"name": "capabilities"},
                    story_quality_report=None,
                    character_media_database={"name": "characters"},
                    character_media_projections={"name": "projections"},
                    character_media_search_index={"name": "search"},
                    character_media_quality_report=None,
                ),
                publications=SiteProjectionPublications(
                    character_audio=[],
                    character_textures=[],
                ),
                quality_report={},
            )
            old_projection = {
                "contentReleaseId": "jp-old-release",
                "region": "global",
                "channel": "staging",
                "locale": "ja",
                "catalogPath": "/data/releases/jp-old-release/ja/catalog.json",
            }
            (root / "generated").mkdir()
            (root / "generated/release-index.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "active": old_projection,
                        "projections": [old_projection],
                    }
                ),
                encoding="utf-8",
            )

            write_release_projection(
                generated_root=root / "generated",
                public_data_root=root / "public",
                context=context,
                build=build,
            )

            release_root = root / "generated/releases/jp-test-release/ja"
            self.assertEqual(
                sorted(path.name for path in release_root.iterdir()),
                [
                    "arena-rank.json",
                    "band-items.json",
                    "card-detail-projections.json",
                    "catalog.json",
                    "character-media-projections.json",
                    "character-media-search-index.json",
                    "character-media.json",
                    "game-database.json",
                    "game-modes.json",
                    "global-systems.json",
                    "high-score-rating.json",
                    "media-capabilities.json",
                    "story-database.json",
                    "story-search-index.json",
                    "unified-search-index.json",
                ],
            )
            release_index = json.loads(
                (root / "generated/release-index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(release_index["projections"]), 1)
            self.assertEqual(
                release_index["projections"][0]["contentReleaseId"],
                "jp-test-release",
            )

    def test_release_projection_rejects_an_invalid_registered_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = SiteProjectionBuild(
                catalog={"schemaVersion": 5},
                artifacts=SiteProjectionArtifacts(
                    music_chart_data={},
                    game_database={},
                    game_modes={},
                    global_systems={},
                    high_score_rating={},
                    arena_rank={},
                    unified_search_index={},
                    card_detail_projections={},
                    band_item_database={},
                    band_item_quality_report=None,
                    story_database=None,
                    story_search_index=None,
                    media_capabilities=None,
                    story_quality_report=None,
                    character_media_database=None,
                    character_media_projections=None,
                    character_media_search_index=None,
                    character_media_quality_report=None,
                ),
                publications=SiteProjectionPublications(
                    character_audio=[],
                    character_textures=[],
                ),
                quality_report={},
            )

            with self.assertRaisesRegex(
                ArtifactValidationError,
                "schemaVersion must be 6",
            ):
                write_release_projection(
                    generated_root=root / "generated",
                    public_data_root=root / "public",
                    context=BuildContext(
                        content_release_id="release",
                        region="global",
                        channel="staging",
                        locale="ja",
                        release={},
                    ),
                    build=build,
                )

    def test_builder_has_no_module_level_fixed_release(self) -> None:
        self.assertFalse(hasattr(catalog_builder, "RELEASE"))
        source = Path(catalog_builder.__file__).read_text(encoding="utf-8")
        self.assertNotIn("global-staging-6521695fc2fd2dfc", source)


    def test_enriches_manifest_with_container_paths(self) -> None:
        manifest = {
            "assets": [
                {
                    "bundle": "bundle/a",
                    "path_id": 42,
                    "type": "Texture2D",
                },
                {
                    "bundle": "bundle/a",
                    "path_id": 43,
                    "type": "Sprite",
                    "container_path": "Assets/existing.png",
                },
            ]
        }
        self.assertEqual(
            bundle_record_keys(manifest),
            {"bundle/a": {(42, "Texture2D"), (43, "Sprite")}},
        )

        counts = enrich_manifest(
            manifest,
            {
                (
                    "bundle/a",
                    42,
                    "Texture2D",
                ): "Assets/AddressableResources/MemberCard/3/member_full.png"
            },
        )

        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["already_present"], 1)
        self.assertEqual(counts["missing"], 0)
        self.assertEqual(
            manifest["assets"][0]["container_path"],
            "Assets/AddressableResources/MemberCard/3/member_full.png",
        )

    def test_classifies_known_resource_names(self) -> None:
        self.assertEqual(classify_kind("item_icon_star", "Assets/AddressableResources/Item/common/item_icon_star.png"), "item")
        self.assertEqual(classify_kind("character_thumbnail"), "character")
        self.assertEqual(classify_kind("member_full"), "card")
        self.assertEqual(classify_kind("adv_bkg_stage_0001"), "background")
        self.assertEqual(classify_kind("ui_story_banner"), "banner")
        self.assertEqual(classify_kind("jkt_001_100001"), "cover")
        self.assertEqual(
            classify_kind(
                "item_icon_3",
                "Assets/AddressableResources/Item/3/item_icon_3.png",
            ),
            "item",
        )
        self.assertEqual(
            classify_kind(
                "icon_skill_scoreup",
                "Assets/AddressableResources/Character/Skill/"
                "icon_skill_scoreup.png",
            ),
            "skill",
        )
        self.assertEqual(
            classify_kind(
                "item_icon_3",
                "Assets/Unverified/Item/3/item_icon_3.png",
            ),
            "other",
        )
        self.assertEqual(
            classify_kind(
                "band_item",
                (
                    "Assets/AddressableResources/Band/1/"
                    "BandItem/101/band_item.png"
                ),
            ),
            "band_item",
        )
        self.assertEqual(
            classify_kind(
                "stamp_illust_tomori_001",
                (
                    "Assets/AddressableResources/Stamp/illust/"
                    "stamp_illust_tomori_001.png"
                ),
            ),
            "stamp",
        )
        self.assertEqual(classify_kind("opaque_name"), "other")

    def test_selects_functional_card_taxonomy_assets_without_extra_limit(self) -> None:
        records = [
            {
                "source_file": Path(f"/tmp/background-{index}.png"),
                "name": f"adv_bkg_{index}",
                "kind": "background",
                "container_path": f"Assets/Background/{index}.png",
            }
            for index in range(60)
        ]
        records.extend(
            [
                {
                    "source_file": Path("/tmp/type-1.png"),
                    "name": "sp_icon_live_music_type_1",
                    "kind": classify_kind(
                        "sp_icon_live_music_type_1",
                        "Assets/AddressableResources/UI/Atlas/"
                        "FixUiSpriteAtlas.spriteatlasv2",
                    ),
                    "container_path": (
                        "Assets/AddressableResources/UI/Atlas/"
                        "FixUiSpriteAtlas.spriteatlasv2"
                    ),
                },
                {
                    "source_file": Path("/tmp/rarity-star.png"),
                    "name": "sp_card_rarity_star",
                    "kind": classify_kind(
                        "sp_card_rarity_star",
                        "Assets/AddressableResources/UI/Atlas/"
                        "FixUiSpriteAtlas.spriteatlasv2",
                    ),
                    "container_path": (
                        "Assets/AddressableResources/UI/Atlas/"
                        "FixUiSpriteAtlas.spriteatlasv2"
                    ),
                },
                {
                    "source_file": Path("/tmp/band-logo.png"),
                    "name": "band_logo",
                    "kind": classify_kind(
                        "band_logo",
                        "Assets/AddressableResources/Band/2/band_logo.png",
                    ),
                    "container_path": (
                        "Assets/AddressableResources/Band/2/band_logo.png"
                    ),
                },
            ]
        )

        selected = select_catalog_records(records, extra_limit=0)

        self.assertEqual(
            {record["source_file"].name for record in selected},
            {"type-1.png", "rarity-star.png", "band-logo.png"},
        )

    def test_stable_id_uses_bundle_and_object_id(self) -> None:
        record = {"bundle": "bundle/a", "path_id": 42}
        self.assertEqual(stable_id("asset", record), stable_id("asset", record))
        self.assertNotEqual(
            stable_id("asset", record),
            stable_id("asset", {"bundle": "bundle/a", "path_id": 43}),
        )

    def test_selects_band_items_and_stamps_for_publication(self) -> None:
        selected = select_catalog_records(
            [
                {
                    "source_file": Path("/tmp/band-item.png"),
                    "name": "band_item",
                    "kind": "band_item",
                    "container_path": (
                        "Assets/AddressableResources/Band/1/"
                        "BandItem/101/band_item.png"
                    ),
                },
                {
                    "source_file": Path("/tmp/stamp.png"),
                    "name": "stamp_illust_tomori_001",
                    "kind": "stamp",
                    "container_path": (
                        "Assets/AddressableResources/Stamp/illust/"
                        "stamp_illust_tomori_001.png"
                    ),
                },
            ]
        )

        self.assertEqual(
            {record["kind"] for record in selected},
            {"band_item", "stamp"},
        )

    def test_build_catalog_merges_supplemental_extracted_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "extracted"
            extracted.mkdir()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"assets": []}), encoding="utf-8")
            supplemental = root / "stamp-extracted"
            (supplemental / "textures").mkdir(parents=True)
            (supplemental / "textures/stamp.png").write_bytes(b"stamp")
            (supplemental / "manifest.json").write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "bundle": "stamp.bundle",
                                "path_id": 20,
                                "type": "Texture2D",
                                "name": "stamp_illust_tomori_001",
                                "width": 512,
                                "height": 512,
                                "container_path": (
                                    "Assets/AddressableResources/Stamp/illust/"
                                    "stamp_illust_tomori_001.png"
                                ),
                                "exported_file": "textures/stamp.png",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            overrides = root / "overrides"
            overrides.mkdir()

            build = build_catalog(
                manifest,
                extracted,
                root / "unused-master",
                overrides,
                root / "media",
                skip_media=True,
                assets_only=True,
                supplemental_extracted_roots=[supplemental],
                build_context=BuildContext(
                    content_release_id="global-staging-test-release",
                    region="global",
                    channel="staging",
                    locale="ja",
                    release={
                        "id": "global-staging-test-release",
                        "region": "global",
                        "channel": "staging",
                        "locale": "ja",
                        "packageName": "fixture.jp",
                        "versionName": "1.0.0",
                        "versionCode": 1,
                        "unityVersion": "fixture",
                        "label": "JP fixture",
                    },
                ),
            )

            self.assertIsInstance(build, SiteProjectionBuild)
            catalog = build.catalog
            self.assertNotIn("_musicChartData", build.quality_report)
            self.assertEqual(len(catalog["assets"]), 1)
            self.assertEqual(catalog["assets"][0]["kind"], "stamp")
            self.assertEqual(
                catalog["assets"][0]["containerPath"],
                (
                    "Assets/AddressableResources/Stamp/illust/"
                    "stamp_illust_tomori_001.png"
                ),
            )

    def test_override_rejects_unknown_entity(self) -> None:
        with self.assertRaises(CatalogError):
            apply_entity_overrides(
                [{"id": "known", "displayName": "Known"}],
                {"unknown": {"displayName": "No"}},
                "character",
            )

    def test_override_rejects_verified_relationship_fields(self) -> None:
        with self.assertRaises(CatalogError):
            apply_entity_overrides(
                [{"id": "character-1", "bandId": "band-1"}],
                {"character-1": {"bandId": "band-2"}},
                "character",
                protected_fields=("bandId",),
            )

    def test_parses_only_verified_resource_paths(self) -> None:
        identity = parse_resource_identity(
            "Assets/AddressableResources/MemberCard/26/member_full.png"
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.kind, "member_card")
        self.assertEqual(identity.asset_id, 26)
        self.assertIsNone(
            parse_resource_identity(
                "Assets/AddressableResources/MemberCard/not-an-id/"
                "member_full.png"
            )
        )

    def test_validator_detects_dangling_relationship(self) -> None:
        catalog = {
            "assets": [{"id": "asset-1"}],
            "bands": [{"id": "band-1", "characterIds": ["character-1"]}],
            "characters": [
                {
                    "id": "character-1",
                    "profileAssetId": "asset-1",
                    "bandId": "band-1",
                    "memberCardIds": ["member-card-1"],
                    "featuredSupportCardIds": [],
                }
            ],
            "memberCards": [
                {
                    "id": "member-card-1",
                    "primaryAssetId": "asset-1",
                    "characterId": "missing",
                }
            ],
            "supportCards": [],
        }
        self.assertIn(
            "member-card-1 has missing character missing",
            validate_catalog(catalog),
        )

    def test_builds_verified_master_entities_and_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "extracted"
            textures = extracted / "textures"
            textures.mkdir(parents=True)
            files = {
                "character_thumbnail": textures / "character-thumbnail.png",
                "character_sprite": textures / "character-sprite.png",
                "member_full": textures / "member.png",
                "snap_full": textures / "support.png",
            }
            for name, path in files.items():
                path.write_bytes(name.encode("utf-8"))
            manifest = {
                "assets": [
                    {
                        "bundle": "character-bundle",
                        "path_id": 1,
                        "type": "Texture2D",
                        "name": "character_thumbnail",
                        "width": 270,
                        "height": 740,
                        "container_path": (
                            "Assets/AddressableResources/Character/Image/1/"
                            "character_thumbnail.png"
                        ),
                        "exported_file": "textures/character-thumbnail.png",
                    },
                    {
                        "bundle": "character-bundle",
                        "path_id": 2,
                        "type": "Texture2D",
                        "name": "character_sprite",
                        "width": 1536,
                        "height": 1536,
                        "container_path": (
                            "Assets/AddressableResources/Character/Image/1/"
                            "character_sprite.png"
                        ),
                        "exported_file": "textures/character-sprite.png",
                    },
                    {
                        "bundle": "member-bundle",
                        "path_id": 3,
                        "type": "Texture2D",
                        "name": "member_full",
                        "width": 1440,
                        "height": 1920,
                        "container_path": (
                            "Assets/AddressableResources/MemberCard/1/"
                            "member_full.png"
                        ),
                        "exported_file": "textures/member.png",
                    },
                    {
                        "bundle": "support-bundle",
                        "path_id": 4,
                        "type": "Texture2D",
                        "name": "snap_full",
                        "width": 1920,
                        "height": 1080,
                        "container_path": (
                            "Assets/AddressableResources/SupportCard/1/"
                            "snap_full.png"
                        ),
                        "exported_file": "textures/support.png",
                    },
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            overrides = root / "overrides"
            overrides.mkdir()
            master = root / "master"
            master.mkdir()

            def write_master(name: str, rows: list[dict[str, object]]) -> None:
                (master / f"{name}.json").write_text(
                    json.dumps({"_allData": rows}),
                    encoding="utf-8",
                )

            write_master(
                "MasterCharacter",
                [
                    {
                        "_id": 1,
                        "_nameTextID": "character_name",
                        "_shortNameTextID": "character_short",
                        "_enDisplayNameTextId": "character_en",
                        "_bandID": 1,
                        "_bandPart": "Vo.",
                        "_birthdayMonth": 11,
                        "_birthdayDay": 22,
                        "_mainColorCode": "#77BBDD",
                        "_subColorCode": "#FFFFFF",
                    }
                ],
            )
            write_master(
                "MasterBand",
                [
                    {
                        "_id": 1,
                        "_nameTextID": "band_name",
                        "_descriptionTextID": "band_description",
                        "_mainColorCode": "#3388BB",
                        "_subColorCode": "#FFFFFF",
                    }
                ],
            )
            write_master(
                "MasterMemberCard",
                [
                    {
                        "_id": 1,
                        "_assetID": 1,
                        "_nameTextID": "character_name",
                        "_subtitleTextID": "member_subtitle",
                        "_characterID": 1,
                        "_rarity": 2,
                        "_cardType": 3,
                        "_performancePowerMax": 100,
                        "_technicPowerMax": 200,
                        "_visualPowerMax": 300,
                        "_memberCardLevelGroup": 0,
                        "_memberCardAwakeGroup": 0,
                        "_memberCardAwakeResourceGroup": 0,
                        "_memberCardRankGroup": 0,
                        "_rankUpItemID": 0,
                        "_leaderSkillID": 0,
                        "_liveSkillID": 0,
                        "_gekisouSkillID": 0,
                        "_liveSkillLevelResourceGroup": 0,
                        "_gekisouSkillLevelResourceGroup": 0,
                        "_linkSkillLevelResourceGroup": 0,
                        "_startAt": "2024-08-01 14:00:00",
                    }
                ],
            )
            write_master(
                "MasterSupportCard",
                [
                    {
                        "_id": 1,
                        "_assetID": 1,
                        "_nameTextID": "support_name",
                        "_descriptionTextID": "support_description",
                        "_characterIDs": [1],
                        "_rarity": 2,
                        "_cardType": 4,
                        "_performancePowerMax": 400,
                        "_technicPowerMax": 500,
                        "_visualPowerMax": 600,
                        "_supportCardLevelGroup": 0,
                        "_supportCardRankGroup": 0,
                        "_rankUpItemID": 0,
                        "_supportSkillId01": 0,
                        "_supportSkillId02": 0,
                        "_gekisouSupportSkillId01": 0,
                        "_gekisouSupportSkillId02": 0,
                        "_startAt": "2024-08-01 14:00:00",
                    }
                ],
            )
            write_master(
                "MasterText",
                [
                    {
                        "_id": "character_name",
                        "_japanese": "高松 燈",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "character_short",
                        "_japanese": "燈",
                        "_english": "Tomori",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "character_en",
                        "_japanese": "",
                        "_english": "Tomori Takamatsu",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "band_name",
                        "_japanese": "MyGO!!!!!",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "band_description",
                        "_japanese": "Band description",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "member_subtitle",
                        "_japanese": "今、ここにいる",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "support_name",
                        "_japanese": "高松 燈",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                    {
                        "_id": "support_description",
                        "_japanese": "人間になりたくて",
                        "_english": "",
                        "_simplifiedChinese": "",
                        "_traditionalChinese": "",
                    },
                ],
            )
            for table_name in (
                *GAME_DATABASE_TABLES,
                *STORY_TABLES,
                *CHARACTER_MEDIA_TABLES,
                *BAND_ITEM_TABLES,
            ):
                table_path = master / f"{table_name}.json"
                if not table_path.exists():
                    write_master(table_name, [])

            build = build_catalog(
                manifest_path,
                extracted,
                master,
                overrides,
                root / "media",
                skip_media=True,
                extra_limit=0,
                build_context=BuildContext(
                    content_release_id="global-staging-test-release",
                    region="global",
                    channel="staging",
                    locale="ja",
                    release={
                        "id": "global-staging-test-release",
                        "region": "global",
                        "channel": "staging",
                        "locale": "ja",
                        "packageName": "fixture.jp",
                        "versionName": "1.0.0",
                        "versionCode": 1,
                        "unityVersion": "fixture",
                        "label": "JP fixture",
                    },
                ),
            )
            catalog = build.catalog
            report = build.quality_report

            self.assertEqual(report["characterCount"], 1)
            self.assertEqual(report["memberCardCount"], 1)
            self.assertEqual(report["supportCardCount"], 1)
            self.assertEqual(
                catalog["memberCards"][0]["characterId"], "character-1"
            )
            self.assertEqual(
                catalog["supportCards"][0]["featuredCharacterIds"],
                ["character-1"],
            )
            self.assertEqual(
                catalog["characters"][0]["memberCardIds"],
                ["member-card-1"],
            )
            self.assertEqual(
                catalog["characters"][0]["featuredSupportCardIds"],
                ["support-card-1"],
            )
            self.assertEqual(report["pendingCharacterCount"], 0)
            self.assertEqual(report["pendingMemberCardCount"], 0)
            self.assertEqual(report["pendingSupportCardCount"], 0)
            self.assertEqual(catalog["release"]["id"], "global-staging-test-release")
            self.assertEqual(catalog["projectionContext"]["locale"], "ja")


if __name__ == "__main__":
    unittest.main()
