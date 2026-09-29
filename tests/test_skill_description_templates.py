import unittest

from tools.game_database import REQUIRED_TABLES, _build_skills, _render_skill_template


class SkillDescriptionTemplateTest(unittest.TestCase):
    def render(self, template, duration=2):
        tables = {name: [] for name in REQUIRED_TABLES}
        tables.update({
            "MasterBand": [{"_id": 1, "_nameTextID": "band_name"}],
            "MasterSkillTarget": [{"_id": 3, "_skillTargetType": 3, "_bandID": 1}],
            "MasterSkillCondition": [
                {"_id": 178, "_conditionTargetIDs": [3], "_conditionValues": [80]},
                {"_id": 179, "_conditionValues": [12]},
            ],
            "MasterSkillConditionSet": [{"_id": 195, "_group": 186, "_conditionIds": [178, 179]}],
            "MasterSkillCumulativeCondition": [{"_id": 7, "_conditionValues": [20]}],
            "MasterSupportSkill": [{"_id": 31, "_descriptionTextFormatID": "description"}],
            "MasterSupportSkillEffect": [{
                "_id": 301, "_supportSkillID": 31, "_level": 1,
                "_skillEffectType": 12006, "_activationTimeSecond": duration,
                "_skillConditionGroup": 186, "_skillTriggerConditionGroup": 186,
                "_skillCumulativeConditionID": 7, "_effectLimitCount": 3,
            }],
            "MasterSkillEffectSetting": [{"_skillEffectType": 12006}],
        })
        texts = {"description": {"_simplifiedChinese": template}, "band_name": {"_simplifiedChinese": "MyGO!!!!!"}}
        skills, _ = _build_skills(tables, texts, {}, {186}, {7})
        return skills[0]["levels"][0]["renderedSummary"]

    def test_band_condition_is_resolved_through_effect_set_and_target(self):
        self.assertEqual(
            self.render("若为「{effects[0].con[0][0].targets[0].name}」成员，对GOOD也生效"),
            "若为「MyGO!!!!!」成员，对GOOD也生效",
        )

    def test_condition_values_preserve_set_and_condition_indexes(self):
        self.assertEqual(self.render("{effects[0].con[0][0].values[0]:F0}% / {effects[0].tCon[0][1].values[0]} / {effects[0].cCon.values[0]}"), "80% / 12 / 20")

    def test_duration_branches_use_the_current_level_effect(self):
        template = '{0 < effects[0].time ? "JUST激奏开始后" : ""}{0 < effects[0].time ? effects[0].time ~ "秒内" : "JUST激奏期间"}'
        self.assertEqual(self.render(template), "JUST激奏开始后2秒内")
        self.assertEqual(self.render(template, duration=0), "JUST激奏期间")

    def test_unknown_paths_remain_unresolved_instead_of_guessing(self):
        self.assertEqual(self.render("{effects[0].con[0][8].values[0]}"), "〔指定条件〕")
        self.assertEqual(_render_skill_template('{__import__("os")}', []), ("〔指定条件〕", False))
