import unittest

from tools.game_database import _attach_skill_resource_profiles, _build_card_projections
from tools.master_catalog import MasterData, build_master_entities


class CardDetailContentTest(unittest.TestCase):
    def test_shared_growth_profiles_do_not_collect_other_cards_skill_costs(self):
        growth_cost = {"itemId": "item-10", "amount": 60, "usageKind": "member_rank", "stage": 2}
        skill_cost = {"itemId": "item-20", "amount": 10, "usageKind": "skill_level", "stage": 2}
        growth = {"profile": {"id": "shared", "materialRequirements": [growth_cost]}, "summary": {}}
        tables = {"MasterMemberCard": [
            {"_id": 1, "_leaderSkillID": 0, "_gekisouSkillID": 0, "_liveSkillID": 1, "_liveSkillLevelResourceGroup": 1},
            {"_id": 2, "_leaderSkillID": 0, "_gekisouSkillID": 0, "_liveSkillID": 1, "_liveSkillLevelResourceGroup": 1},
        ], "MasterSupportCard": []}
        skills = [{"id": "live-skill-1", "name": "Live", "relatedCardIds": [], "levels": [], "interpretationStatus": "identified"}]
        projections = _build_card_projections(tables, skills, {"member-card-1": growth, "member-card-2": growth})
        profiles = {1: {"materialRequirements": [skill_cost], "sourceCardIds": [], "relatedSkillIds": []}}
        _attach_skill_resource_profiles(projections, profiles, {20: {"usages": []}})
        self.assertEqual(growth["profile"]["materialRequirements"], [growth_cost])
        for card in projections["memberCards"]:
            self.assertEqual(card["materialSummary"], [growth_cost, skill_cost])

    def test_support_diary_uses_game_text_and_preserves_paragraphs(self):
        master = MasterData(
            characters={1: {"_id": 1, "_bandID": 1}}, bands={1: {"_id": 1}}, member_cards={},
            support_cards={
                1: {"_id": 1, "_characterIDs": [1], "_diaryTextID": "diary"},
                2: {"_id": 2, "_characterIDs": [1], "_diaryTextID": ""},
            }, texts={"diary": {"_simplifiedChinese": "第一行\r\n\r\n第二段", "_english": "My diary"}},
        )
        entities, _ = build_master_entities(master, [], {}, "test-release")
        self.assertEqual(entities["supportCards"][0]["diary"], "第一行\n\n第二段")
        self.assertEqual(entities["supportCards"][1]["diary"], "")
        english, _ = build_master_entities(master, [], {}, "test-release", "en")
        self.assertEqual(english["supportCards"][0]["diary"], "My diary")
