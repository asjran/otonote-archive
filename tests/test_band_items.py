from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.band_items import BandItemError, build_band_items


def write_table(
    root: Path,
    name: str,
    rows: list[dict[str, object]],
) -> None:
    (root / f"{name}.json").write_text(
        json.dumps({"_allData": rows}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_minimal_tables(root: Path) -> None:
    write_table(
        root,
        "MasterText",
        [
            {"_id": "Band_Name_mygo", "_japanese": "MyGO!!!!!"},
            {"_id": "Band_Item_101", "_japanese": "燈のマイク"},
            {
                "_id": "Band_Item_Description_101",
                "_japanese": (
                    "MyGO!!!!!の全パラメータ "
                    "<style=color_positive>+{0}%Up</style>"
                ),
            },
            {
                "_id": "Skill_Effect_Name_1",
                "_japanese": "メンバーの全パラメータアップ",
            },
        ],
    )
    write_table(
        root,
        "MasterBand",
        [
            {
                "_id": 1,
                "_nameTextID": "Band_Name_mygo",
                "_mainColorCode": "#3388BB",
                "_subColorCode": "#FFFFFF",
            }
        ],
    )
    write_table(
        root,
        "MasterBandItem",
        [
            {
                "_id": 101,
                "_nameTextId": "Band_Item_101",
                "_descriptionTextId": "Band_Item_Description_101",
                "_bandId": 1,
                "_resourceGroupId": 1000,
                "_displayOrder": 3,
            }
        ],
    )
    write_table(
        root,
        "MasterBandItemLevel",
        [
            {
                "_id": 10101,
                "_bandItemId": 101,
                "_level": 1,
                "_playerRank": 1,
            },
            {
                "_id": 10110,
                "_bandItemId": 101,
                "_level": 10,
                "_playerRank": 5,
            },
        ],
    )
    write_table(
        root,
        "MasterBandItemSkillEffect",
        [
            {
                "_id": 1,
                "_bandItemId": 101,
                "_level": 1,
                "_skillTargetIDs": [3],
                "_skillEffectType": 1000,
                "_effectValue": 50,
            },
            {
                "_id": 10,
                "_bandItemId": 101,
                "_level": 10,
                "_skillTargetIDs": [3],
                "_skillEffectType": 1000,
                "_effectValue": 500,
            },
        ],
    )
    write_table(
        root,
        "MasterSkillEffectSetting",
        [
            {
                "_id": 1,
                "_skillEffectType": 1000,
                "_nameTextId": "Skill_Effect_Name_1",
                "_phase": 2,
            }
        ],
    )
    write_table(
        root,
        "MasterSkillTarget",
        [
            {
                "_id": 3,
                "_skillTargetType": 3,
                "_characterID": 0,
                "_bandID": 1,
            }
        ],
    )


class BandItemsTest(unittest.TestCase):
    def test_resolves_materials_by_resource_group_and_target_level(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_minimal_tables(root)
            write_table(root, "MasterItem", [
                {"_id": 3, "_nameTextId": "coin", "_imagePath": "Item/common/coin"},
                {"_id": 7, "_nameTextId": "fragment", "_imagePath": "Item/fragment/small"},
            ])
            texts = json.loads((root / "MasterText.json").read_text())["_allData"]
            write_table(root, "MasterText", texts + [
                {"_id": "coin", "_simplifiedChinese": "金币"},
                {"_id": "fragment", "_simplifiedChinese": "碎片（小）"},
            ])
            write_table(root, "MasterSkillLevelResource", [
                {"_id": 1, "_group": 1000, "_level": 1, "_itemID": 3, "_count": 2500},
                {"_id": 2, "_group": 1000, "_level": 10, "_itemID": 3, "_count": 25000},
                {"_id": 3, "_group": 1000, "_level": 10, "_itemID": 7, "_count": 200},
                {"_id": 4, "_group": 1001, "_level": 10, "_itemID": 3, "_count": 99999},
                {"_id": 5, "_group": 1000, "_level": 31, "_itemID": 3, "_count": 140000},
            ])
            built = build_band_items(root, "test-release", [{
                "containerPath": "Assets/AddressableResources/Item/common/coin.png",
                "previewUrl": "/media/coin.webp",
            }])
            levels = built.database["items"][0]["levels"]
            self.assertEqual(levels[0]["upgradeMaterials"][0]["amount"], 2500)
            self.assertEqual(levels[1]["upgradeMaterials"], [
                {"itemId": "item-3", "name": "金币", "amount": 25000,
                 "previewUrl": "/media/coin.webp", "sourceResourceId": 2},
                {"itemId": "item-7", "name": "碎片（小）", "amount": 200,
                 "previewUrl": None, "sourceResourceId": 3},
            ])

    def test_missing_materials_remain_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_minimal_tables(root)
            built = build_band_items(root, "test-release")
            self.assertIsNone(built.database["items"][0]["levels"][0]["upgradeMaterials"])
            self.assertTrue(any("no material resources" in warning for warning in built.warnings))

    def test_rejects_invalid_or_duplicate_material_requirements(self) -> None:
        for amount, item_id, duplicate in [(-1, 3, False), (1, 999, False), (1, 3, True)]:
            with self.subTest(amount=amount, item_id=item_id, duplicate=duplicate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_minimal_tables(root)
                write_table(root, "MasterItem", [{"_id": 3}])
                row = {"_id": 1, "_group": 1000, "_level": 1, "_itemID": item_id, "_count": amount}
                write_table(root, "MasterSkillLevelResource", [row, row] if duplicate else [row])
                with self.assertRaises(BandItemError):
                    build_band_items(root, "test-release")

    def test_preserves_current_levels_when_future_effects_are_preloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_minimal_tables(root)
            path = root / "MasterBandItemSkillEffect.json"
            table = json.loads(path.read_text(encoding="utf-8"))
            table["_allData"].append(
                {"_id": 31, "_bandItemId": 101, "_level": 31,
                 "_skillTargetIDs": [3], "_skillEffectType": 1000,
                 "_effectValue": 310}
            )
            path.write_text(json.dumps(table), encoding="utf-8")
            built = build_band_items(root, "test-release", [])
            self.assertEqual(len(built.database["items"][0]["levels"]), 2)
            self.assertEqual(built.quality_report["futureEffectCount"], 1)
            self.assertTrue(any("beyond current level cap" in warning for warning in built.warnings))

    def test_builds_level_effects_and_verified_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_minimal_tables(root)
            container = (
                "Assets/AddressableResources/Band/1/"
                "BandItem/101/band_item.png"
            )

            built = build_band_items(
                root,
                "test-release",
                [
                    {
                        "id": "asset-band-item-101",
                        "containerPath": container,
                        "previewUrl": "/media/previews/asset-band-item-101.webp",
                    }
                ],
            )

            item = built.database["items"][0]
            self.assertEqual(item["id"], "band-item-101")
            self.assertEqual(item["name"], "燈のマイク")
            self.assertEqual(item["bandName"], "MyGO!!!!!")
            self.assertEqual(item["assetId"], "asset-band-item-101")
            self.assertEqual(item["catalogStatus"], "identified")
            self.assertEqual(
                item["levels"][0]["renderedSummary"],
                "MyGO!!!!!の全パラメータ +0.5%Up",
            )
            self.assertEqual(
                item["levels"][-1]["renderedSummary"],
                "MyGO!!!!!の全パラメータ +5%Up",
            )
            self.assertEqual(
                item["levels"][-1]["effects"][0],
                {
                    "sourceEffectId": 10,
                    "effectType": 1000,
                    "effectName": "メンバーの全パラメータアップ",
                    "rawValue": 500,
                    "displayValue": "5%",
                    "targetMasterIds": [3],
                    "targetBandIds": ["band-1"],
                    "interpretationStatus": "identified",
                },
            )


if __name__ == "__main__":
    unittest.main()
