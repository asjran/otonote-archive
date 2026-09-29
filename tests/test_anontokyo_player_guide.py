from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.anontokyo_player_guide import (  # noqa: E402
    _format_delivery_effect,
    _player_effect_name,
    _project_furniture,
    build_anontokyo_player_guide,
)
from tools.anontokyo_projection import build_anontokyo_projection  # noqa: E402


FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/anontokyo/minimal"


class AnonTokyoPlayerGuideTest(unittest.TestCase):
    def test_normalizes_delivery_effect_spacing_from_global_text(self) -> None:
        self.assertEqual(
            _format_delivery_effect("配送时间    -{0}%", "10"),
            "配送时间 -10%",
        )

    def test_cleans_format_placeholders_from_player_effect_names(self) -> None:
        self.assertEqual(
            _player_effect_name("顾客上限 <color=#F63D1B>+{0}人</color>"),
            "顾客上限提升",
        )
        self.assertEqual(
            _player_effect_name("额外获得{0}%银币"),
            "额外银币",
        )

    def _build(
        self,
        root: Path,
        *,
        formula_policy: dict | None = None,
        master_root: Path | None = None,
        map_config_path: Path | None = None,
    ):
        projection = root / "projection"
        build_anontokyo_projection(
            master_root=master_root or FIXTURE_ROOT / "master",
            catalog_path=FIXTURE_ROOT / "catalog.json",
            map_config_path=map_config_path,
            output_root=projection,
            source_release_id="global-staging-fixture",
            generated_at="2026-08-05T00:00:00Z",
        )
        output = root / "player-guide"
        result = build_anontokyo_player_guide(
            projection_root=projection,
            output_root=output,
            formula_policy=formula_policy,
        )
        return output, result

    def test_projects_studio_from_map_and_visible_furniture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(
                Path(temporary),
                map_config_path=FIXTURE_ROOT / "MapConfig_1.json",
            )

            studio = json.loads((output / "studio.json").read_text())
            furniture = {item["name"]: item for item in studio["furniture"]}
            self.assertEqual(studio["schemaVersion"], 2)
            self.assertEqual(studio["map"]["grid"], {"width": 4, "height": 4})
            self.assertEqual(
                studio["storeSizes"],
                [{"level": 1, "width": 4, "height": 4}],
            )
            self.assertEqual(furniture["货架"]["footprint"], {"width": 1, "height": 2})
            self.assertEqual(furniture["货架"]["directions"], [0])
            self.assertEqual(
                studio["initialLayout"],
                [
                    {
                        "instanceId": "layout-instance-ad6fc4f0011b",
                        "furnitureId": furniture["货架"]["id"],
                        "x": 1,
                        "y": 1,
                        "direction": 0,
                    }
                ],
            )
            self.assertIn("studio.json", result.manifest["files"])
            self.assertEqual(
                studio["scene"]["warehouse"],
                {
                    "id": "warehouse",
                    "name": "补货仓库",
                    "x": 0,
                    "y": 0,
                    "direction": 0,
                    "footprint": {"width": 3, "height": 3},
                    "imageKey": "AT_Map_Outdoor_Warehouse_Full",
                    "fixed": True,
                },
            )
            self.assertEqual(
                studio["scene"]["deliveryStart"],
                {"x": 3, "y": 3},
            )
            self.assertEqual(
                studio["scene"]["staticObjects"],
                [
                    {
                        "id": "scene-object-aec706f78254",
                        "x": 0,
                        "y": 3,
                        "direction": 0,
                        "footprint": {"width": 1, "height": 1},
                        "imageKey": "AT_Map_Outdoor_Tile (1)",
                    }
                ],
            )
            self.assertEqual(
                studio["modes"]["gameFaithful"]["defaultLayout"],
                studio["initialLayout"],
            )
            self.assertEqual(studio["modes"]["free"]["defaultLayout"], [])
            self.assertEqual(len(studio["deliveryOptions"]), 3)
            serialized = json.dumps(studio, ensure_ascii=False)
            self.assertNotIn("MasterAT", serialized)
            self.assertNotIn('"configId"', serialized)

    def test_projects_hidden_stage_subtype_for_studio_preview(self) -> None:
        furniture, hidden, by_source = _project_furniture(
            {
                "mainTypes": [
                    {"id": "2", "visible": True, "name": "室内装饰"},
                ],
                "subTypes": [
                    {"id": "18", "visible": False, "name": "舞台"},
                ],
                "records": [
                    {
                        "id": "11001",
                        "name": "MyGO 舞台",
                        "typeId": "2",
                        "subTypeId": "18",
                        "mediaKey": "AT_Icon_Fever_Stage0",
                        "sceneMediaKey": "AT_Map_Stage1_Img_Bottom",
                        "size": [3, 4],
                        "direction": [0, 3],
                        "condition": {"type": 1, "value": 1},
                        "purchase": {},
                        "sale": {},
                    }
                ],
            }
        )

        self.assertEqual(hidden, 0)
        self.assertEqual(len(furniture["records"]), 1)
        self.assertEqual(by_source["11001"]["subCategory"], "舞台")
        self.assertEqual(
            by_source["11001"]["sceneImageKey"],
            "AT_Map_Stage1_Img_Bottom",
        )

    def test_builds_twelve_player_modules_behind_one_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))

            manifest = json.loads((output / "manifest.json").read_text())
            store = json.loads((output / "store.json").read_text())
            goods = json.loads((output / "goods.json").read_text())
            tasks = json.loads((output / "tasks.json").read_text())
            staff = json.loads((output / "staff.json").read_text())

            self.assertEqual(result.output_root, output)
            self.assertEqual(manifest["sourceReleaseId"], "global-staging-fixture")
            self.assertEqual(
                set(manifest["files"]),
                {
                    "store.json",
                    "growth.json",
                    "goods.json",
                    "customers.json",
                    "wardrobe.json",
                    "inspiration.json",
                    "furniture.json",
                    "themes.json",
                    "stages.json",
                    "chats.json",
                    "tasks.json",
                    "staff.json",
                    "guide.json",
                    "mechanics.json",
                },
            )
            self.assertEqual(store["levels"][0]["level"], 1)
            self.assertIn(
                {"label": "玩家等级要求", "value": 5, "unit": "级"},
                store["levels"][0]["upgradeRequirements"],
            )
            self.assertEqual(goods["records"][0]["name"], "合成连衣裙")
            self.assertEqual(goods["records"][0]["category"], "服装")
            self.assertEqual(goods["records"][0]["tags"], ["可爱"])
            self.assertEqual(tasks["records"][0]["condition"], "上架合成连衣裙2次")
            self.assertEqual(tasks["records"][0]["rewards"][0]["name"], "经验")
            self.assertEqual(
                tasks["records"][0]["rewards"][0]["imageKey"],
                "AT_Common_Icon_Experience",
            )
            self.assertEqual(staff["records"][0]["name"], "测试店员")
            self.assertEqual(
                staff["records"][0]["imageKey"],
                "AT_Main_Avatar_Test",
            )
            self.assertEqual(staff["records"][0]["abilities"][0]["effect"], "+5%")
            self.assertEqual(
                staff["records"][0]["abilities"][0]["roleInclination"]["name"],
                "收银",
            )
            self.assertEqual(
                staff["records"][0]["abilities"][0]["roleInclination"]["value"],
                5,
            )
            self.assertEqual(
                [role["id"] for role in staff["assignmentStudio"]["roles"]],
                ["cashier", "sales", "restock"],
            )
            self.assertEqual(
                staff["assignmentStudio"]["capacityByLevel"][0]["capacities"],
                {"cashier": 1, "sales": 1, "restock": 1},
            )
            self.assertEqual(result.report["hiddenGoods"], 0)

    def test_projects_visible_wardrobe_with_associated_goods_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))
            wardrobe = json.loads((output / "wardrobe.json").read_text())

            self.assertEqual(len(wardrobe["records"]), 2)
            headwear = next(item for item in wardrobe["records"] if item["type"] == "头饰")
            self.assertEqual(headwear["name"], "测试系列[头饰]")
            self.assertEqual(headwear["series"], "测试系列")
            self.assertEqual(headwear["characters"][0]["name"], "测试店员")
            self.assertEqual(headwear["associatedGoods"][0]["name"], "合成连衣裙")
            serialized = json.dumps(wardrobe, ensure_ascii=False)
            self.assertNotIn("解锁来源", serialized)
            self.assertNotIn("取得方式", serialized)
            self.assertEqual(result.report["recordCounts"]["wardrobe"], 2)
            self.assertEqual(result.report["hiddenWardrobe"], 1)

    def test_projects_contiguous_inspiration_tiers_and_delivery_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))
            inspiration = json.loads((output / "inspiration.json").read_text())
            store = json.loads((output / "store.json").read_text())

            self.assertEqual(
                inspiration["records"][1],
                {
                    "id": "inspiration-87369f6f3894",
                    "minimum": 20,
                    "maximum": 39,
                    "purchaseCount": 1,
                    "extraPurchaseChance": 40,
                    "nextMinimum": 40,
                },
            )
            self.assertEqual(
                [(item["name"], item["effect"]) for item in store["deliveryOptions"]],
                [
                    ("气球配送员", None),
                    ("猫咪配送员", "配送时间 -10%"),
                    ("狗狗配送员", "下单数量 +20%"),
                ],
            )
            self.assertEqual(result.report["recordCounts"]["inspirationTiers"], 3)

    def test_projects_player_growth_and_capacity_without_unknown_rewards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))
            growth = json.loads((output / "growth.json").read_text())

            self.assertEqual(
                growth["records"][0],
                {
                    "id": "growth-a716b1fcdf1d",
                    "level": 1,
                    "requiredExp": 0,
                    "expToNext": 60,
                    "staminaLimit": 10,
                    "customerLimit": 3,
                    "customerTiers": [1],
                },
            )
            self.assertEqual(growth["warehouseSteps"][0]["capacity"], 20)
            self.assertEqual(
                growth["warehouseSteps"][0]["cost"],
                {"name": "银币", "count": 100},
            )
            self.assertEqual(growth["safeDepositSteps"][0]["capacity"], 10)
            serialized = json.dumps(growth, ensure_ascii=False)
            self.assertNotIn("reward", serialized)
            self.assertEqual(result.report["recordCounts"]["playerLevels"], 2)

    def test_projects_character_customer_preferences_and_matching_goods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))
            customers = json.loads((output / "customers.json").read_text())

            first = next(
                item
                for item in customers["records"]
                if item["character"]["name"] == "测试店员"
            )
            self.assertEqual(first["preferences"], ["可爱", "都市"])
            self.assertEqual(first["matchingGoods"][0]["name"], "合成连衣裙")
            self.assertEqual(first["matchingGoods"][0]["matchedTags"], ["可爱"])
            self.assertEqual(first["band"], "测试乐队")
            self.assertEqual(result.report["recordCounts"]["characterCustomers"], 2)
            self.assertEqual(result.report["hiddenCustomers"], 0)

    def test_projects_visible_furniture_as_player_facing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))

            furniture = json.loads((output / "furniture.json").read_text())

            records = {item["name"]: item for item in furniture["records"]}
            self.assertEqual(
                records["货架"],
                {
                    "id": "furniture-d92a1d96bc04",
                    "name": "货架",
                    "category": "设施",
                    "subCategory": "陈列",
                    "imageKey": "AT_Icon_Decoration_Test",
                    "size": "1 × 2",
                    "purchase": 20,
                    "sale": 2,
                    "limit": 2,
                    "unlock": "店铺等级 1",
                    "related": records["货架"].get("related", {}),
                },
            )
            self.assertEqual(records["试衣镜"]["unlock"], "店铺等级 2")
            self.assertEqual(result.report["recordCounts"]["furniture"], 2)
            self.assertEqual(result.report["hiddenFurniture"], 1)
            self.assertIn("furniture.json", result.manifest["files"])

    def test_projects_theme_relations_through_visible_furniture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))

            themes = json.loads((output / "themes.json").read_text())
            furniture = json.loads((output / "furniture.json").read_text())
            records_by_name = {item["name"]: item for item in furniture["records"]}

            self.assertEqual(themes["records"][0]["name"], "测试主题")
            self.assertEqual(themes["records"][0]["imageKey"], "AT_Theme_Test")
            self.assertEqual(
                themes["records"][0]["requiredFurniture"],
                [
                    {
                        "id": records_by_name["货架"]["id"],
                        "name": "货架",
                        "imageKey": "AT_Icon_Decoration_Test",
                        "size": "1 × 2",
                    }
                ],
            )
            self.assertEqual(
                themes["records"][0]["unlockedFurniture"],
                [
                    {
                        "id": records_by_name["试衣镜"]["id"],
                        "name": "试衣镜",
                        "imageKey": "AT_Icon_Decoration_Mirror",
                        "size": "1 × 1",
                    }
                ],
            )
            self.assertEqual(
                themes["records"][0]["reward"],
                {"name": "经验", "count": 5, "imageKey": "AT_Common_Icon_Experience"},
            )
            self.assertEqual(result.report["recordCounts"]["themes"], 1)
            self.assertEqual(result.report["unresolvedThemeFurniture"], 0)

    def test_projects_stage_without_claiming_server_availability_or_buff_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))

            stages = json.loads((output / "stages.json").read_text())
            stage = stages["records"][0]

            self.assertEqual(stage["name"], "测试乐队舞台")
            self.assertEqual(stage["band"], "测试乐队")
            self.assertEqual(stage["members"][0]["name"], "测试店员")
            self.assertEqual(stage["music"]["name"], "测试舞台曲")
            self.assertEqual(stage["music"]["duration"], "45 秒")
            self.assertEqual(stage["music"]["unlock"], "默认解锁")
            self.assertEqual(
                stage["feverEffects"],
                [{"name": "顾客刷新上限提升", "imageKey": "AT_Common_Icon_Star"}],
            )
            self.assertEqual(stages["effects"], stage["feverEffects"])
            serialized = json.dumps(stages, ensure_ascii=False)
            self.assertNotIn("2026-04-01", serialized)
            self.assertNotIn("rawValue", serialized)
            self.assertNotIn("availability", serialized)
            self.assertEqual(result.report["recordCounts"]["stages"], 1)
            self.assertEqual(result.report["hiddenStages"], 0)

    def test_projects_chat_order_without_speaker_guess_and_hides_missing_monologue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))

            chats = json.loads((output / "chats.json").read_text())
            record = chats["records"][0]

            self.assertEqual(
                [character["name"] for character in record["characters"]],
                ["测试店员", "终端店员"],
            )
            self.assertEqual(record["band"], "测试乐队")
            self.assertEqual(
                record["scenes"][0],
                {"kind": "cashier", "label": "收银", "lines": ["第一句", "第二句"]},
            )
            self.assertNotIn("speaker", json.dumps(record, ensure_ascii=False))
            self.assertEqual(
                [(item["role"], item["text"]) for item in chats["monologues"]],
                [("收银", "收银独白"), ("导购", "导购独白"), ("待机", "待机独白")],
            )
            serialized = json.dumps(chats, ensure_ascii=False)
            self.assertNotIn("chat_cashier_1", serialized)
            self.assertNotIn("mono_cashier", serialized)
            self.assertNotIn("3001", serialized)
            self.assertEqual(result.report["recordCounts"]["chatCombinations"], 1)
            self.assertEqual(result.report["recordCounts"]["monologues"], 3)
            self.assertEqual(result.report["hiddenMonologues"], 1)

    def test_marks_chat_text_reused_by_different_character_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master = root / "master"
            shutil.copytree(FIXTURE_ROOT / "master", master)
            chat_path = master / "MasterATCharChat.json"
            chat = json.loads(chat_path.read_text())
            reused = dict(chat["_allData"][0])
            reused["_id"] = "2_1"
            chat["_allData"].append(reused)
            chat_path.write_text(json.dumps(chat, ensure_ascii=False))

            output, result = self._build(root, master_root=master)
            chats = json.loads((output / "chats.json").read_text())

            self.assertEqual(result.report["reusedChatCombinations"], 2)
            self.assertTrue(all(item["reusedText"] for item in chats["records"]))
            self.assertTrue(
                all("可能尚未最终对应" in item["contentNote"] for item in chats["records"])
            )

    def test_output_is_a_player_only_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self._build(Path(temporary))
            serialized = "\n".join(
                path.read_text() for path in sorted(output.glob("*.json"))
            )

            for forbidden in (
                "MasterAT",
                "sourceTable",
                "sourceId",
                "sourceFields",
                "interpretationStatus",
                "warnings",
                "abilityId",
                "taskTypeId",
                "categoryId",
                "tagIds",
                "goods_test",
                str(FIXTURE_ROOT),
            ):
                self.assertNotIn(forbidden, serialized)

            for document in output.glob("*.json"):
                self._assert_no_private_keys(json.loads(document.read_text()))

    def _assert_no_private_keys(self, value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertFalse(key.startswith("_"), key)
                self._assert_no_private_keys(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_no_private_keys(child)

    def test_formula_values_remain_absent_until_units_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(Path(temporary))
            record = json.loads((output / "goods.json").read_text())["records"][0]

            self.assertNotIn("profitPerUnit", record)
            self.assertNotIn("profitPerHour", record)
            self.assertEqual(result.report["formulaCapabilities"]["goodsProfit"], "blocked")

    def test_verified_unit_policy_enables_profit_without_changing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, result = self._build(
                Path(temporary),
                formula_policy={
                    "purchaseCost": "per_unit",
                    "saleCoin": "per_unit",
                    "deliveryDuration": "seconds_per_batch",
                    "batchSize": "purchase_item_count",
                },
            )
            record = json.loads((output / "goods.json").read_text())["records"][0]

            self.assertEqual(record["profitPerUnit"], 2)
            self.assertEqual(record["profitPerHour"], 1200)
            self.assertEqual(result.report["formulaCapabilities"]["goodsProfit"], "verified")


if __name__ == "__main__":
    unittest.main()
