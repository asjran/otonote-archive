from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.game_database import GameDatabaseError, build_game_database


REQUIRED_TABLES = (
    "MasterText",
    "MasterBand",
    "MasterCharacter",
    "MasterMemberCard",
    "MasterSupportCard",
    "MasterLeaderSkill",
    "MasterLeaderSkillEffect",
    "MasterLiveSkill",
    "MasterLiveSkillEffect",
    "MasterSupportSkill",
    "MasterSupportSkillEffect",
    "MasterGekisouSkill",
    "MasterGekisouSkillEffect",
    "MasterGekisouSupportSkill",
    "MasterGekisouSupportSkillEffect",
    "MasterSkillCondition",
    "MasterSkillConditionSet",
    "MasterSkillCumulativeCondition",
    "MasterSkillEffectGroup",
    "MasterSkillEffectSetting",
    "MasterSkillTarget",
    "MasterSkillLevelResource",
    "MasterSkillIcon",
    "MasterMemberCardLevel",
    "MasterMemberCardLevelLimit",
    "MasterMemberCardRank",
    "MasterMemberCardAwake",
    "MasterMemberCardAwakeResource",
    "MasterSupportCardLevel",
    "MasterSupportCardRank",
    "MasterItem",
)


def write_tables(
    root: Path,
    values: dict[str, list[dict[str, object]]],
) -> None:
    import json

    for name in REQUIRED_TABLES:
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": values.get(name, [])}),
            encoding="utf-8",
        )


class GameDatabaseTest(unittest.TestCase):
    def test_rejects_missing_required_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(
                GameDatabaseError,
                r"missing Master table: .*MasterText\.json",
            ):
                build_game_database(root, "test-release")

    def test_builds_skill_and_member_card_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterText": [
                        {
                            "_id": "skill_name",
                            "_japanese": "表现提升",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                        {
                            "_id": "skill_description",
                            "_japanese": (
                                "效果"
                                "{effects[0].value/100:F1}%"
                            ),
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                        {
                            "_id": "effect_name",
                            "_japanese": "成员表现提升",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                    ],
                    "MasterMemberCard": [
                        {
                            "_id": 1,
                            "_memberCardLevelGroup": 0,
                            "_memberCardAwakeGroup": 0,
                            "_memberCardAwakeResourceGroup": 0,
                            "_memberCardRankGroup": 0,
                            "_rankUpItemID": 0,
                            "_leaderSkillID": 10,
                            "_liveSkillID": 0,
                            "_gekisouSkillID": 0,
                            "_liveSkillLevelResourceGroup": 0,
                            "_gekisouSkillLevelResourceGroup": 0,
                            "_linkSkillLevelResourceGroup": 0,
                        }
                    ],
                    "MasterLeaderSkill": [
                        {
                            "_id": 10,
                            "_nameTextID": "skill_name",
                            "_descriptionTextFormatID": "skill_description",
                            "_skillIconID": 1,
                        }
                    ],
                    "MasterLeaderSkillEffect": [
                        {
                            "_id": 101,
                            "_leaderSkillID": 10,
                            "_level": 1,
                            "_skillConditionGroup": 0,
                            "_skillTargetIDs": [3],
                            "_skillEffectType": 1002,
                            "_effectValue": 1000,
                            "_skillCumulativeConditionID": 0,
                            "_effectExecuteLimitCount": 0,
                            "_effectExecuteLimitResetConditionGroup": 0,
                            "_icon": "",
                        },
                        {
                            "_id": 102,
                            "_leaderSkillID": 10,
                            "_level": 1,
                            "_skillConditionGroup": 0,
                            "_skillTargetIDs": [3],
                            "_skillEffectType": 1002,
                            "_effectValue": 2000,
                            "_skillCumulativeConditionID": 0,
                            "_effectExecuteLimitCount": 0,
                            "_effectExecuteLimitResetConditionGroup": 0,
                            "_icon": "",
                        },
                    ],
                    "MasterSkillEffectSetting": [
                        {
                            "_id": 1,
                            "_skillEffectType": 1002,
                            "_nameTextId": "effect_name",
                            "_phase": 2,
                        }
                    ],
                    "MasterSkillTarget": [
                        {
                            "_id": 3,
                            "_skillTargetType": 3,
                            "_characterID": 0,
                            "_bandID": 1,
                            "_cardType": 0,
                            "_tagID": 0,
                            "_judgement": -1,
                            "_liveMusicType": 0,
                            "_skillType": -1,
                            "_skillGroupID": 0,
                            "_gekisouMissionType": 0,
                            "_liveSkillCategories": [],
                            "_gekisouSkillCategories": [],
                        }
                    ],
                    "MasterSkillIcon": [
                        {
                            "_id": 1,
                            "_normalIconAssetName": "skill-test-icon",
                        }
                    ],
                },
            )

            built = build_game_database(
                root,
                "test-release",
                {"skill-test-icon": "asset-skill-test"},
            )

            skill = built.database["skills"][0]
            self.assertEqual(skill["id"], "leader-skill-10")
            self.assertEqual(skill["iconAssetId"], "asset-skill-test")
            self.assertEqual(skill["iconStatus"], "identified")
            self.assertEqual(skill["publicationStatus"], "public")
            self.assertEqual(skill["levels"][0]["renderedSummary"], "效果10.0%")
            self.assertEqual(
                [
                    effect["sourceOrder"]
                    for effect in skill["levels"][0]["effects"]
                ],
                [0, 1],
            )
            self.assertEqual(
                built.card_projections["memberCards"][0]["skillRefs"],
                [
                    {
                        "slot": "leader",
                        "skillId": "leader-skill-10",
                        "levelResourceGroup": 0,
                    }
                ],
            )

    def test_archives_unreferenced_skill_with_missing_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterText": [
                        {
                            "_id": "test_skill_name",
                            "_japanese": "検証用効果無し",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        }
                    ],
                    "MasterLiveSkill": [
                        {
                            "_id": 99998,
                            "_nameTextID": "test_skill_name",
                            "_descriptionTextFormatID": "",
                            "_skillIconID": 1,
                        }
                    ],
                    "MasterSkillIcon": [
                        {"_id": 1, "_normalIconAssetName": "missing-icon"}
                    ],
                },
            )

            built = build_game_database(root, "test-release")
            skill = built.database["skills"][0]

            self.assertEqual(skill["iconStatus"], "source_missing")
            self.assertEqual(skill["publicationStatus"], "archive_only")
            self.assertEqual(skill["publicationReason"], "unreferenced_skill")
            self.assertEqual(
                built.database["quality"]["unexplainedMissingSkillIconCount"],
                0,
            )

    def test_ignores_unreferenced_orphan_effect_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterLeaderSkillEffect": [
                        {
                            "_id": 90170,
                            "_leaderSkillID": 90045,
                            "_level": 1,
                            "_skillTargetIDs": [],
                            "_skillEffectType": 0,
                        }
                    ]
                },
            )

            built = build_game_database(root, "test-release")

            self.assertEqual(built.database["skills"], [])
            self.assertIn(
                "MasterLeaderSkillEffect effect 90170 references missing "
                "leader skill 90045",
                built.warnings,
            )

    def test_preserves_multiple_condition_sets_in_one_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterSkillCondition": [
                        {
                            "_id": 61,
                            "_conditionType": 100,
                            "_conditionValues": [10],
                            "_isPositive": True,
                            "_conditionTargetIDs": [],
                        },
                        {
                            "_id": 62,
                            "_conditionType": 101,
                            "_conditionValues": [20],
                            "_isPositive": False,
                            "_conditionTargetIDs": [],
                        },
                    ],
                    "MasterSkillConditionSet": [
                        {
                            "_id": 1001,
                            "_group": 37,
                            "_conditionIds": [61],
                        },
                        {
                            "_id": 1002,
                            "_group": 37,
                            "_conditionIds": [62],
                        },
                    ],
                },
            )

            built = build_game_database(root, "test-release")

            self.assertEqual(
                built.database["conditionGroups"],
                [
                    {
                        "groupId": 37,
                        "sets": [
                            {
                                "sourceSetId": 1001,
                                "conditionIds": ["skill-condition-61"],
                            },
                            {
                                "sourceSetId": 1002,
                                "conditionIds": ["skill-condition-62"],
                            },
                        ],
                        "combinationStatus": "unverified",
                    }
                ],
            )

    def test_ignores_unreferenced_orphan_condition_set_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterSkillConditionSet": [
                        {
                            "_id": 260,
                            "_group": 250,
                            "_conditionIds": [249],
                        }
                    ]
                },
            )

            built = build_game_database(root, "test-release")

            self.assertEqual(built.database["conditionGroups"], [])
            self.assertIn(
                "skill condition set 260 references missing conditions [249]",
                built.warnings,
            )

    def test_builds_separate_growth_profiles_and_item_usages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterText": [
                        {
                            "_id": "item_10",
                            "_japanese": "成员碎片",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                        {
                            "_id": "item_20",
                            "_japanese": "支援碎片",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                    ],
                    "MasterMemberCard": [
                        {
                            "_id": 1,
                            "_rarity": 2,
                            "_memberCardLevelGroup": 1,
                            "_memberCardAwakeGroup": 1,
                            "_memberCardAwakeResourceGroup": 2,
                            "_memberCardRankGroup": 1,
                            "_rankUpItemID": 10,
                            "_leaderSkillID": 0,
                            "_liveSkillID": 0,
                            "_gekisouSkillID": 0,
                            "_liveSkillLevelResourceGroup": 0,
                            "_gekisouSkillLevelResourceGroup": 0,
                            "_linkSkillLevelResourceGroup": 0,
                        }
                    ],
                    "MasterSupportCard": [
                        {
                            "_id": 2,
                            "_rarity": 4,
                            "_characterIDs": [6],
                            "_supportCardLevelGroup": 3,
                            "_supportCardRankGroup": 4,
                            "_rankUpItemID": 999,
                            "_supportSkillId01": 0,
                            "_supportSkillId02": 0,
                            "_gekisouSupportSkillId01": 0,
                            "_gekisouSupportSkillId02": 0,
                        }
                    ],
                    "MasterCharacter": [
                        {
                            "_id": 6,
                            "_bandID": 2,
                        }
                    ],
                    "MasterBand": [
                        {
                            "_id": 2,
                            "_rankUpItemIdForRarityR": 17,
                            "_rankUpItemIdForRaritySR": 18,
                            "_rankUpItemIdForRaritySSR": 20,
                            "_rankUpItemIdForRarityBD": 21,
                        }
                    ],
                    "MasterMemberCardLevel": [
                        {
                            "_id": 1,
                            "_group": 1,
                            "_level": 1,
                            "_exp": 0,
                            "_performanceRate": 4086,
                            "_technicRate": 4086,
                            "_visualRate": 4086,
                        },
                        {
                            "_id": 2,
                            "_group": 1,
                            "_level": 2,
                            "_exp": 100,
                            "_performanceRate": 4200,
                            "_technicRate": 4200,
                            "_visualRate": 4200,
                        },
                    ],
                    "MasterMemberCardLevelLimit": [
                        {
                            "_id": 1,
                            "_rarity": 2,
                            "_awakeCount": 1,
                            "_limitLevel": 2,
                        }
                    ],
                    "MasterMemberCardRank": [
                        {
                            "_id": 1,
                            "_group": 1,
                            "_rank": 1,
                            "_requiredRankUpItemCount": 50,
                            "_performanceRate": 250,
                            "_technicRate": 250,
                            "_visualRate": 250,
                            "_leaderSkillLevel": 1,
                            "_musicTypeBonusRate": 0,
                            "_musicTagBonusRate": 0,
                        }
                    ],
                    "MasterMemberCardAwake": [
                        {
                            "_id": 1,
                            "_group": 1,
                            "_awakeCount": 1,
                            "_performanceRate": 0,
                            "_technicRate": 0,
                            "_visualRate": 0,
                        }
                    ],
                    "MasterMemberCardAwakeResource": [
                        {
                            "_id": 1,
                            "_group": 2,
                            "_awakeCount": 1,
                            "_itemId": 10,
                            "_count": 5,
                        }
                    ],
                    "MasterSupportCardLevel": [
                        {
                            "_id": 3,
                            "_group": 3,
                            "_level": 1,
                            "_exp": 0,
                            "_performanceRate": 5000,
                            "_technicRate": 5000,
                            "_visualRate": 5000,
                        }
                    ],
                    "MasterSupportCardRank": [
                        {
                            "_id": 4,
                            "_group": 4,
                            "_rank": 1,
                            "_limitLevel": 10,
                            "_requiredRankUpItemCount": 8,
                            "_supportSkillLevel": 1,
                            "_gekisouSupportSkillLevel": 1,
                            "_supportSkill01Level": 1,
                            "_supportSkill02Level": 0,
                            "_gekisouSupportSkill01Level": 1,
                            "_gekisouSupportSkill02Level": 0,
                            "_cardTypeLinkBonusRate": 0,
                        }
                    ],
                    "MasterItem": [
                        {
                            "_id": 10,
                            "_inventoryDisplayGroup": 3,
                            "_type": 9,
                            "_imagePath": "Item/10/item_icon_10",
                            "_nameTextId": "item_10",
                            "_phoneticNameTextId": "",
                            "_descriptionTextId": "",
                            "_value": 1,
                            "_max": 0,
                            "_orderNum": 10,
                            "_displayTargetIds": [],
                            "_startAt": "",
                            "_endAt": "",
                        },
                        {
                            "_id": 20,
                            "_inventoryDisplayGroup": 3,
                            "_type": 9,
                            "_imagePath": "Item/20/item_icon_20",
                            "_nameTextId": "item_20",
                            "_phoneticNameTextId": "",
                            "_descriptionTextId": "",
                            "_value": 1,
                            "_max": 0,
                            "_orderNum": 20,
                            "_displayTargetIds": [],
                            "_startAt": "",
                            "_endAt": "",
                        },
                    ],
                },
            )

            built = build_game_database(
                root,
                "test-release",
                {"Item/10/item_icon_10": "asset-item-10"},
            )

            member = built.card_projections["memberCards"][0]
            support = built.card_projections["supportCards"][0]
            self.assertTrue(member["growthProfileId"].startswith("member-growth-"))
            self.assertTrue(
                support["growthProfileId"].startswith("support-growth-")
            )
            self.assertNotEqual(
                member["growthProfileId"],
                support["growthProfileId"],
            )
            items = {item["id"]: item for item in built.database["items"]}
            self.assertEqual(items["item-10"]["iconAssetId"], "asset-item-10")
            self.assertEqual(
                {
                    usage["usageKind"]
                    for usage in items["item-10"]["usages"]
                },
                {"member_rank", "member_awake"},
            )
            self.assertEqual(
                {
                    usage["usageKind"]
                    for usage in items["item-20"]["usages"]
                },
                {"support_rank"},
            )
            self.assertEqual(member["growthSummary"]["maxLevel"], 2)
            self.assertEqual(support["growthSummary"]["maxLevel"], 10)

    def test_selects_support_rank_material_by_band_and_rarity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            material_ids = [101, 102, 103, 201, 202, 203]
            support_cards = []
            expected_by_card = {}
            for index, (_band_id, character_id, base_item_id) in enumerate(
                ((1, 1, 100), (2, 6, 200))
            ):
                for rarity_offset, rarity in enumerate((2, 3, 4), start=1):
                    card_id = index * 3 + rarity_offset
                    support_cards.append(
                        {
                            "_id": card_id,
                            "_rarity": rarity,
                            "_characterIDs": [character_id],
                            "_supportCardLevelGroup": 1,
                            "_supportCardRankGroup": 1,
                            "_rankUpItemID": 999,
                            "_supportSkillId01": 0,
                            "_supportSkillId02": 0,
                            "_gekisouSupportSkillId01": 0,
                            "_gekisouSupportSkillId02": 0,
                        }
                    )
                    expected_by_card[f"support-card-{card_id}"] = (
                        f"item-{base_item_id + rarity_offset}"
                    )
            support_cards.append(
                {
                    "_id": 7,
                    "_rarity": 10,
                    "_characterIDs": [1, 6],
                    "_supportCardLevelGroup": 1,
                    "_supportCardRankGroup": 1,
                    "_supportSkillId01": 0,
                    "_supportSkillId02": 0,
                    "_gekisouSupportSkillId01": 0,
                    "_gekisouSupportSkillId02": 0,
                }
            )
            write_tables(
                root,
                {
                    "MasterBand": [
                        {
                            "_id": 1,
                            "_rankUpItemIdForRarityR": 101,
                            "_rankUpItemIdForRaritySR": 102,
                            "_rankUpItemIdForRaritySSR": 103,
                            "_rankUpItemIdForRarityBD": 104,
                        },
                        {
                            "_id": 2,
                            "_rankUpItemIdForRarityR": 201,
                            "_rankUpItemIdForRaritySR": 202,
                            "_rankUpItemIdForRaritySSR": 203,
                            "_rankUpItemIdForRarityBD": 204,
                        },
                    ],
                    "MasterCharacter": [
                        {"_id": 1, "_bandID": 1},
                        {"_id": 6, "_bandID": 2},
                    ],
                    "MasterSupportCard": support_cards,
                    "MasterSupportCardLevel": [
                        {
                            "_id": 1,
                            "_group": 1,
                            "_level": 1,
                            "_exp": 0,
                            "_performanceRate": 5000,
                            "_technicRate": 5000,
                            "_visualRate": 5000,
                        }
                    ],
                    "MasterSupportCardRank": [
                        {
                            "_id": 1,
                            "_group": 1,
                            "_rank": 1,
                            "_limitLevel": 10,
                            "_requiredRankUpItemCount": 1,
                        }
                    ],
                    "MasterItem": [
                        {
                            "_id": item_id,
                            "_inventoryDisplayGroup": 3,
                            "_type": 9,
                            "_imagePath": "",
                            "_nameTextId": "",
                            "_phoneticNameTextId": "",
                            "_descriptionTextId": "",
                            "_value": 1,
                            "_max": 0,
                            "_orderNum": item_id,
                            "_displayTargetIds": [],
                            "_startAt": "",
                            "_endAt": "",
                        }
                        for item_id in material_ids
                    ],
                },
            )

            built = build_game_database(root, "test-release")
            profiles = {
                card_id: next(
                    profile
                    for profile in built.database["growthProfiles"]
                    if card_id in profile["sourceCardIds"]
                )
                for card_id in expected_by_card
            }

            self.assertEqual(
                {
                    card_id: profile["rankItemId"]
                    for card_id, profile in profiles.items()
                },
                expected_by_card,
            )
            cross_band = next(
                projection
                for projection in built.card_projections["supportCards"]
                if projection["cardId"] == "support-card-7"
            )
            self.assertEqual(cross_band["projectionStatus"], "partial")
            self.assertIsNone(cross_band["growthProfileId"])
            self.assertTrue(any("support-card-7 spans bands" in warning for warning in built.warnings))

    def test_projects_skill_level_materials_from_card_resource_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tables(
                root,
                {
                    "MasterText": [
                        {
                            "_id": "skill_name",
                            "_japanese": "得分提升",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                        {
                            "_id": "skill_description",
                            "_japanese": "{effects[0].value/100:F1}%",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                        {
                            "_id": "item_name",
                            "_japanese": "技能素材",
                            "_simplifiedChinese": "",
                            "_english": "",
                            "_traditionalChinese": "",
                        },
                    ],
                    "MasterMemberCard": [
                        {
                            "_id": 1,
                            "_memberCardLevelGroup": 0,
                            "_memberCardAwakeGroup": 0,
                            "_memberCardAwakeResourceGroup": 0,
                            "_memberCardRankGroup": 0,
                            "_rankUpItemID": 0,
                            "_leaderSkillID": 0,
                            "_liveSkillID": 20,
                            "_gekisouSkillID": 0,
                            "_liveSkillLevelResourceGroup": 5,
                            "_gekisouSkillLevelResourceGroup": 0,
                            "_linkSkillLevelResourceGroup": 0,
                        }
                    ],
                    "MasterLiveSkill": [
                        {
                            "_id": 20,
                            "_nameTextID": "skill_name",
                            "_descriptionTextFormatID": "skill_description",
                            "_skillIconID": 0,
                            "_skillCategories": [1],
                        }
                    ],
                    "MasterLiveSkillEffect": [
                        {
                            "_id": 201,
                            "_liveSkillID": 20,
                            "_level": 2,
                            "_skillTargetIDs": [],
                            "_skillEffectType": 2000,
                            "_effectValue": 2000,
                        }
                    ],
                    "MasterSkillLevelResource": [
                        {
                            "_id": 1,
                            "_group": 5,
                            "_level": 2,
                            "_itemID": 10,
                            "_count": 4,
                        }
                    ],
                    "MasterItem": [
                        {
                            "_id": 10,
                            "_inventoryDisplayGroup": 1,
                            "_type": 6,
                            "_imagePath": "",
                            "_nameTextId": "item_name",
                            "_phoneticNameTextId": "",
                            "_descriptionTextId": "",
                            "_value": 1,
                            "_max": 99,
                            "_orderNum": 1,
                            "_displayTargetIds": [],
                            "_startAt": "",
                            "_endAt": "",
                        }
                    ],
                },
            )

            built = build_game_database(root, "test-release")

            skill_ref = built.card_projections["memberCards"][0]["skillRefs"][0]
            self.assertEqual(
                skill_ref["materialRequirements"],
                [
                    {
                        "itemId": "item-10",
                        "amount": 4,
                        "usageKind": "skill_level",
                        "stage": 2,
                        "sourceEntityId": "skill-resource-group-5",
                        "sourceGroupId": 5,
                        "cardIds": ["member-card-1"],
                        "interpretationStatus": "partial",
                    }
                ],
            )
            item = built.database["items"][0]
            self.assertEqual(item["usages"][0]["usageKind"], "skill_level")
            self.assertEqual(
                built.database["skillLevelResourceProfiles"][0]["groupId"],
                5,
            )


if __name__ == "__main__":
    unittest.main()
