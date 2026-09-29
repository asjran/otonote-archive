from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.anontokyo_projection import (  # noqa: E402
    AnonTokyoProjectionError,
    build_anontokyo_projection,
)


FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/anontokyo/minimal"


class AnonTokyoProjectionTest(unittest.TestCase):
    def test_projects_validated_map_config_for_studio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            result = build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                map_config_path=FIXTURE_ROOT / "MapConfig_1.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            map_document = json.loads((output / "map.json").read_text())
            self.assertEqual(map_document["map"]["grid"], {"width": 4, "height": 4})
            self.assertEqual(map_document["map"]["editableTileIndexes"], list(range(1, 16)))
            self.assertEqual(
                map_document["map"]["initialObjects"],
                [
                    {
                        "instanceId": "9001",
                        "configId": "200",
                        "tileIndex": 9,
                        "direction": 0,
                    }
                ],
            )
            self.assertEqual(map_document["map"]["fixedObjects"][0]["tileIndex"], 0)
            self.assertEqual(result.manifest["recordCounts"]["mapTiles"], 16)
            self.assertEqual(result.manifest["inputSummary"]["mapConfigHash"], map_document["sourceHash"])

    def test_builds_versioned_guide_projection_from_public_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            result = build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            self.assertEqual(result.output_root, output)
            manifest = json.loads((output / "manifest.json").read_text())
            goods = json.loads((output / "goods.json").read_text())
            self.assertEqual(manifest["schemaVersion"], 1)
            self.assertEqual(
                manifest["sourceReleaseId"], "global-staging-fixture"
            )
            self.assertEqual(manifest["recordCounts"]["goods"], 1)
            self.assertEqual(goods["records"][0]["id"], "100")
            self.assertEqual(
                goods["records"][0]["name"]["values"]["zh-CN"],
                "合成连衣裙",
            )
            self.assertEqual(
                manifest["formulaCapabilities"]["goodsProfit"], "blocked"
            )
            self.assertEqual(
                set(manifest["files"]),
                {
                    "decorations.json",
                    "wardrobe.json",
                    "inspiration.json",
                    "themes.json",
                    "stages.json",
                    "chats.json",
                    "goods.json",
                    "media-manifest.json",
                    "progression.json",
                    "staff.json",
                    "tasks.json",
                    "guide.json",
                    "mechanics.json",
                },
            )

    def test_projects_guide_relations_without_unverified_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            goods = json.loads((output / "goods.json").read_text())
            decorations = json.loads((output / "decorations.json").read_text())
            progression = json.loads((output / "progression.json").read_text())
            wardrobe = json.loads((output / "wardrobe.json").read_text())
            inspiration = json.loads((output / "inspiration.json").read_text())
            tasks = json.loads((output / "tasks.json").read_text())
            staff = json.loads((output / "staff.json").read_text())

            self.assertEqual(goods["categories"][0]["goodsIds"], ["100"])
            self.assertEqual(goods["tags"][0]["goodsIds"], ["100"])
            self.assertNotIn("profit", goods["records"][0])
            self.assertEqual(decorations["records"][0]["typeId"], "1")
            self.assertEqual(progression["storeLevels"][0]["id"], "1")
            self.assertEqual(
                [item["id"] for item in wardrobe["records"]],
                ["20001", "20002", "20003"],
            )
            self.assertFalse(wardrobe["records"][2]["visible"])
            self.assertEqual(wardrobe["records"][0]["goodsIds"], ["100"])
            self.assertEqual(
                inspiration["records"][1]["range"], {"minimum": 20, "maximum": 39}
            )
            self.assertEqual(
                progression["deliverySkills"][1]["name"]["values"]["zh-CN"],
                "配送时间 -{0}%",
            )
            self.assertEqual(
                tasks["records"][0]["parameters"],
                [
                    {"name": "goodsid", "value": 100},
                    {"name": "times", "value": 2},
                ],
            )
            self.assertEqual(tasks["rewardIndex"], {"1:4": ["300"]})
            experience = next(
                item for item in tasks["rewardItems"] if item["id"] == "4"
            )
            self.assertEqual(experience["name"]["values"]["zh-CN"], "经验")
            self.assertEqual(
                staff["records"][0]["passiveAbilities"],
                [{"abilityId": 1, "value": 5}],
            )
            self.assertEqual(
                staff["records"][0]["imageKey"],
                "AT_Main_Avatar_Test",
            )
            self.assertEqual(
                staff["passiveAbilities"][0]["value"]["values"]["zh-CN"],
                "+{0}%",
            )
            self.assertNotIn("recommendedRole", staff["records"][0])
            self.assertEqual(progression["playerLevels"][1]["fields"]["exp"], 60)
            self.assertEqual(
                progression["characterCustomers"][0]["fields"]["likeTag2"], 2
            )

    def test_projects_one_theme_with_ordered_furniture_relations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            themes = json.loads((output / "themes.json").read_text())

            self.assertEqual(themes["records"][0]["id"], "1")
            self.assertEqual(
                themes["records"][0]["name"]["values"]["zh-CN"],
                "测试主题",
            )
            self.assertEqual(themes["records"][0]["requiredDecorationIds"], ["200"])
            self.assertEqual(themes["records"][0]["unlockedDecorationIds"], ["202"])
            self.assertEqual(themes["records"][0]["previewKey"], "AT_Theme_Test")
            self.assertEqual(
                themes["records"][0]["reward"],
                [{"raw": "1,4,5", "type": "1", "itemId": "4", "count": "5"}],
            )

    def test_projects_stage_members_music_and_named_fever_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            stages = json.loads((output / "stages.json").read_text())
            stage = stages["records"][0]

            self.assertEqual(stage["bandName"]["values"]["zh-CN"], "测试乐队")
            self.assertEqual(stage["memberIds"], ["1"])
            self.assertEqual(stage["music"]["name"]["values"]["zh-CN"], "测试舞台曲")
            self.assertEqual(stage["music"]["duration"], 45)
            self.assertEqual(
                stage["feverEffects"],
                [
                    {
                        "buffId": "1",
                        "name": stages["buffs"][0]["name"],
                        "iconKey": "AT_Common_Icon_Star",
                        "rawValue": "5",
                    }
                ],
            )
            self.assertEqual(
                stage["availabilityConfig"]["start"],
                "2026-04-01T22:59:59+08:00",
            )

    def test_projects_ordered_chat_lines_and_explicitly_missing_monologue_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "projection"
            build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            chats = json.loads((output / "chats.json").read_text())
            record = chats["records"][0]

            self.assertEqual(record["characterIds"], ["1", "2"])
            self.assertEqual([scene["kind"] for scene in record["scenes"]], ["cashier", "sales", "restocking"])
            self.assertEqual(
                [line["values"]["zh-CN"] for line in record["scenes"][0]["lines"]],
                ["第一句", "第二句"],
            )
            monologue = chats["monologues"][0]
            self.assertEqual(monologue["characterId"], "1")
            self.assertEqual(
                [role["kind"] for role in monologue["roles"]],
                ["cashier", "sales", "restocking", "standby"],
            )
            self.assertIsNone(monologue["roles"][2]["text"])
            self.assertIn("unresolved_monologue:3001", monologue["warnings"])

    def test_rejects_missing_tables_and_never_leaks_input_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master = root / "private/device/master"
            shutil.copytree(FIXTURE_ROOT / "master", master)
            (master / "MasterATGoods.json").unlink()

            with self.assertRaises(AnonTokyoProjectionError) as raised:
                build_anontokyo_projection(
                    master_root=master,
                    catalog_path=FIXTURE_ROOT / "catalog.json",
                    output_root=root / "projection",
                    source_release_id="global-staging-fixture",
                )

            self.assertIn("MasterATGoods", str(raised.exception))
            self.assertNotIn(str(root), str(raised.exception))

    def test_manifest_and_media_projection_contain_no_private_paths_or_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "projection"
            build_anontokyo_projection(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                output_root=output,
                source_release_id="global-staging-fixture",
                generated_at="2026-08-05T00:00:00Z",
            )

            serialized = "\n".join(
                path.read_text() for path in sorted(output.glob("*.json"))
            )
            self.assertNotIn(str(FIXTURE_ROOT), serialized)
            self.assertNotIn("internalId", serialized)
            self.assertNotIn("http://", serialized)
            self.assertNotIn("https://", serialized)


if __name__ == "__main__":
    unittest.main()
