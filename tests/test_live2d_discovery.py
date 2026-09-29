import unittest
from types import SimpleNamespace
from tools.live2d_discovery import discover_models, story_character_labels


class DiscoveryTests(unittest.TestCase):
    def test_catalog_adds_story_and_extra_costumes_without_changing_old_links(self):
        original = '001_adv/adv_live2d_tomori_001_live_01/model/adv_live2d_tomori_001_live_01'
        school = '001_adv/adv_live2d_tomori_001_school_winter_hs/model/adv_live2d_tomori_001_school_winter_hs'
        npc = 'sub_kanata/adv_live2d_sub_kanata_live_01/model/adv_live2d_sub_kanata_live_01'
        costumes = [{'_id': 1002, '_characterID': 1, '_costumeID': 2, '_isDefault': True, '_live2dPath': original}]
        locations = [SimpleNamespace(primary_key='Character/Live2D/' + p) for p in [original, school, npc, npc]]
        models = discover_models(locations, costumes)
        self.assertEqual(len(models), 3)
        self.assertEqual(models[0]['id'], '1002')
        self.assertEqual(models[1]['characterId'], 1)
        self.assertEqual(models[2]['characterId'], 'sub_kanata')
        self.assertEqual(models[2]['category'], 'story')
        self.assertEqual(models, discover_models(list(reversed(locations)), costumes))

    def test_missing_master_resource_is_not_silently_dropped(self):
        costume = {'_id': 1001, '_characterID': 1, '_costumeID': 1, '_isDefault': True, '_live2dPath': 'missing'}
        self.assertEqual(discover_models([], [costume])[0]['id'], '1001')

    def test_story_name_comes_from_explicit_speaker_alias_and_localization(self):
        models = [{'category': 'story', 'characterId': 'sub_mikus_father'}, {'category': 'story', 'characterId': 'sub_unknown'}]
        documents = [{'texts': [{'_id': 'adv_mikurealfather', '_simplifiedChinese': '心玖的生父', '_english': "Miku's Biological Father"}],
                      'root': {'Collection': [{'TargetAssetName': 'sub_mikus_father/outfit/model', 'TargetName': 'mikurealfather'}]}}]
        labels = story_character_labels(models, [], documents)
        self.assertEqual(labels[0]['names']['zh-CN'], '心玖的生父')
        self.assertEqual(labels[0]['nameTextIds'], ['adv_mikurealfather'])
        self.assertEqual(labels[1]['names']['en'], 'unknown')
        self.assertEqual(labels[1]['nameTextIds'], [])
