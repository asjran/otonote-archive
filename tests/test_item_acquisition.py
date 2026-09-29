import json
import tempfile
import unittest
from pathlib import Path
from tools.item_acquisition import build_item_acquisition, build_live_item_drops


class ItemAcquisitionTests(unittest.TestCase):
    def test_only_linked_item_outputs_are_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tables = {
                'MasterText': [{'_id': 'shop', '_text': 'Starter'}],
                'MasterShop': [{'_id': 1, '_nameTextId': 'shop', '_startAt': '2026-09-01'}],
                'MasterShopProduct': [
                    {'_id': 1, '_shopId': 1, '_resourceType': 1, '_resourceId': 7, '_resourceCount': 2, '_isBonus': True},
                    {'_id': 2, '_shopId': 1, '_resourceType': 2, '_resourceId': 7, '_resourceCount': 1},
                    {'_id': 3, '_shopId': 999, '_resourceType': 1, '_resourceId': 8, '_resourceCount': 2},
                ],
                'MasterExchange': [{'_id': 1, '_nameTextId': 'shop', '_paymentResourceId': 99, '_paymentResourceType': 1, '_startAt': '2026-10-01'}],
                'MasterExchangeProduct': [{'_id': 1, '_exchangeId': 1, '_resourceType': 1, '_resourceId': 8, '_resourceCount': 3, '_endAt': '2026-11-01'}],
            }
            for name, rows in tables.items():
                (root / f'{name}.json').write_text(json.dumps({'_allData': rows}))
            actual = build_item_acquisition(root)
            self.assertEqual(set(actual), {'item-7', 'item-8'})
            self.assertEqual(len(actual['item-7']), 1)
            self.assertTrue(actual['item-7'][0]['isBonus'])
            self.assertEqual(actual['item-8'][0]['windows'], [
                {'startAt': '2026-10-01', 'endAt': ''}, {'startAt': '', 'endAt': '2026-11-01'}])
            self.assertEqual(actual['item-8'][0]['count'], 3)

    def test_optional_tables_can_be_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(build_item_acquisition(Path(directory)), {})
            self.assertEqual(build_live_item_drops(Path(directory)), {})

    def test_live_drops_preserve_modes_ranks_and_absolute_probabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def reward(identity, resource_id, rank, probability, count=1, kind=1):
                return {'_id': identity, '_group': 7, '_resourceType': kind, '_resourceId': resource_id,
                        '_liveScoreRank': rank, '_probability': probability, '_resourceCount': count}
            # A rare reward has only 30 probability points in its group, not a
            # 30/30 chance. Identical ids in another resource namespace do not link.
            solo = [reward(1, 22, 2, 15), reward(2, 22, 7, 30),
                    reward(3, 7, 7, 2000, 21), reward(4, 3, 7, 10000, 500),
                    reward(5, 22, 7, 10000, kind=2), reward(6, 99, 7, 0)]
            multi = [reward(1, 7, 7, 2000, 23)]
            for name, rows in [('MasterLiveFreeReward', solo), ('MasterBattleLiveReward', multi)]:
                (root / f'{name}.json').write_text(json.dumps({'_allData': rows}))
            actual = build_live_item_drops(root)
            self.assertEqual(set(actual), {'item-3', 'item-7', 'item-22'})
            self.assertEqual([row['scoreRank'] for row in actual['item-22']], [7, 2])
            self.assertEqual(actual['item-22'][0]['probability'] / actual['item-22'][0]['probabilityBase'], .003)
            self.assertEqual({row['mode']: row['count'] for row in actual['item-7']}, {'solo': 21, 'multi': 23})
            self.assertEqual(actual['item-3'][0]['probability'], 10000)

    def test_invalid_live_probability_fails_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for probability in [None, -1, 10001, True, '30']:
                (root / 'MasterLiveFreeReward.json').write_text(json.dumps({'_allData': [{
                    '_id': 1, '_group': 1, '_resourceType': 1, '_resourceId': 22,
                    '_resourceCount': 1, '_liveScoreRank': 7, '_probability': probability,
                }]}))
                with self.subTest(probability=probability), self.assertRaisesRegex(ValueError, 'Invalid live drop probability'):
                    build_live_item_drops(root)
