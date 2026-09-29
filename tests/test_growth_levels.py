import json
import tempfile
import unittest
from pathlib import Path

from tools.growth_export import ExportError
from tools.growth_levels import GrowthLevels, Thresholds


class GrowthLevelsTests(unittest.TestCase):
    def test_threshold_edges_and_maximum(self):
        levels = Thresholds([{'exp': 210, 'level': 3}, {'exp': 0, 'level': 1},
                             {'exp': 70, 'level': 2}], 'exp', 'level')
        self.assertEqual([levels.resolve(n) for n in [0, 69, 70, 209, 210, 999]],
                         [1, 1, 2, 2, 3, 3])

    def test_invalid_tables_and_values_stop_instead_of_guessing(self):
        for rows in [[{'x': 0, 'l': 0}], [{'x': 1, 'l': 1}],
                     [{'x': 0, 'l': 1}, {'x': 0, 'l': 2}],
                     [{'x': 0, 'l': 1}, {'x': 2, 'l': 3}]]:
            with self.assertRaises(ExportError):
                Thresholds(rows, 'x', 'l')
        levels = Thresholds([{'x': 0, 'l': 1}], 'x', 'l')
        for value in [-1, True, 1.5, '70']:
            with self.assertRaises(ExportError):
                levels.resolve(value)

    def test_projection_preserves_unknown_and_drops_unrelated_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            tables = {'MemberCard': [{'_id': 1, '_memberCardLevelGroup': 1}],
                      'SupportCard': [{'_id': 1, '_supportCardLevelGroup': 1}],
                      'MemberCardLevel': [{'_group': 1, '_exp': 0, '_level': 1}],
                      'SupportCardLevel': [{'_group': 1, '_exp': 0, '_level': 1}],
                      'CharacterRank': [{'_exp': 0, '_rank': 1}, {'_exp': 1, '_rank': 2}],
                      'Vip': [{'_point': 0, '_vipRank': 1}, {'_point': 2000, '_vipRank': 2}]}
            for name, rows in tables.items():
                (p / ('Master' + name + '.json')).write_text(json.dumps({'_allData': rows}))
            resolver = GrowthLevels(p)
            growth = {'memberCards': [{'masterId': 999, 'exp': 0, 'token': 'PRIVATE'}],
                      'supportCards': [], 'characterRanks': [{'characterId': 1, 'exp': 1}],
                      'tgw': {'point': 0}, 'account': 'PRIVATE'}
            before = json.dumps(growth)
            result = resolver.derive(growth)
            self.assertEqual(result['growth']['tgw'], {'level': 1})
            self.assertEqual(result['growth']['memberCards'][0]['level'], None)
            self.assertEqual(result['unresolvedCardCount'], 1)
            self.assertEqual(result['growth']['characterRanks'][0]['rank'], 2)
            self.assertEqual(result['growth']['supportCards'], [])
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(json.dumps(growth), before)
            self.assertTrue(all(v is None for v in resolver.derive({})['growth'].values()))


if __name__ == '__main__':
    unittest.main()
