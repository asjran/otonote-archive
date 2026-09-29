import json
import tempfile
import unittest
from pathlib import Path

from tools.global_systems import build_global_systems, empty_global_systems


class GlobalSystemsTest(unittest.TestCase):
    def test_new_gacha_in_next_master_snapshot_is_projected_without_event_guess(self):
        tables = {
            "MasterText": [
                {"_id": "Gacha_Name_10", "_simplifiedChinese": "新活动招募", "_english": "New Event Gacha"},
                {"_id": "ui_vip_bonus_type_5", "_simplifiedChinese": "练习奖励加成", "_english": "Practice Bonus"},
            ],
            "MasterGacha": [{"_id": 10, "_nameTextId": "Gacha_Name_10", "_priority": 1,
                             "_lotGroupId": 10, "_startAt": "2026/09/28 12:00:00", "_endAt": "",
                             "_productId1": 3, "_productId2": 0, "_productId3": 0, "_productId4": 0,
                             "_bannerAssetName": "Gacha/Banner/new", "_isLimited": True}],
            "MasterGachaLot": [{"_id": 1, "_lotGroupId": 10, "_prizeGroupId": 20}],
            "MasterGachaPrize": [{"_id": 1, "_groupId": 20, "_pickUpType": 2,
                                  "_resourceType": 2, "_resourceId": 100},
                                 {"_id": 2, "_groupId": 20, "_pickUpType": 2,
                                  "_resourceType": 3, "_resourceId": 100},
                                 {"_id": 3, "_groupId": 20, "_pickUpType": 0,
                                  "_resourceType": 3, "_resourceId": 101},
                                 {"_id": 4, "_groupId": 99, "_pickUpType": 2,
                                  "_resourceType": 3, "_resourceId": 102}],
            "MasterGachaProduct": [{"_id": 3, "_drawCount": 10, "_price": 2000, "_itemType": 12}],
            "MasterMemberCard": [{"_id": 100}],
            "MasterSupportCard": [{"_id": 100}, {"_id": 101}, {"_id": 102}],
            "MasterVip": [{"_id": 1, "_vipRank": 1, "_point": 0}],
            "MasterVipRankBonus": [{"_id": 1, "_vipRank": 1, "_vipBonusType": 5, "_value": 100}],
            "MasterVipDailyPoint": [{"_id": 1, "_consecutiveCount": 1, "_point": 100}],
            "MasterVipDailyReward": [],
            "MasterVipRankUpReward": [],
            "MasterOfflineBonusUnit": [{"_id": 1, "_name": "MyGO!!!!!", "_bandId": 1,
                                        "_startAt": "2026/01/01 0:00:00"}],
            "MasterOfflineBonusUnitLevel": [{"_id": 1, "_offlineBonusUnitId": 1,
                                             "_offlineBonusLevel": 1, "_offlineBonusExp": 0,
                                             "_unlockBandRank": 0, "_offlineEfficiencyTime": 3600,
                                             "_offlineLimitTime": 7200, "_earnCoin": 10,
                                             "_earnMemberExp": 5, "_earnSupportExp": 5,
                                             "_earnOfflineBonusExp": 1, "_itemLotGroupId": 1}],
            "MasterOfflineBonusExpFactor": [],
            "MasterOfflineBonusItemLot": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, rows in tables.items():
                (root / f"{name}.json").write_text(json.dumps({"_allData": rows}))
            result = build_global_systems(root, "next-release", "en")
        self.assertEqual(result["sourceReleaseId"], "next-release")
        self.assertEqual(result["gachaPools"][0]["name"], "New Event Gacha")
        self.assertEqual(result["gachaPools"][0]["pickupMemberCardIds"], [100])
        self.assertEqual(result["gachaPools"][0]["pickupSupportCardIds"], [100])
        self.assertEqual(result["gachaPools"][0]["supportCardIds"], [100, 101])
        self.assertEqual(result["gachaPools"][0]["relatedEventIds"], [])
        self.assertEqual(result["vipRanks"][0]["bonuses"][0]["label"], "Practice Bonus")
        self.assertEqual(result["studioUnits"][0]["levels"][0]["limitSeconds"], 7200)

    def test_outside_global_production_is_unavailable(self):
        result = empty_global_systems("jp-release")
        self.assertEqual(result["status"], "unavailable_outside_global_production")
        self.assertFalse(result["gachaPools"])


if __name__ == "__main__":
    unittest.main()
