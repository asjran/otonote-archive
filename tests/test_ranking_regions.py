import copy
import unittest
from unittest.mock import Mock, patch

from tools.collect_player_rankings import RankingClient, run_capture
from tools.global_game_config import GLOBAL_SERVERS
from tools.growth_login import LoginError, message
from tools.ranking_regions import TABLES, manifest_tables, verify_shared_event_tables


class RankingRegionTests(unittest.TestCase):
    def fixture(self, server):
        raw = b''
        for identity in ('global-hmt', server):
            definition = GLOBAL_SERVERS[identity]
            prefix = {'global-hmt':'hk','global-en':'en','global-kr':'kr'}[identity]
            host = ('l14-prod-hk-patch-sirius.gamerfusiontech.com' if prefix == 'hk'
                    else 'l14-prod-sg-patch-sirius.bilibiligame.net')
            row = message(1, definition['name']) + message(8, definition['wireId'])
            row += message(2, 'https://' + host + '/prod/' + prefix + '_' + '1'*32)
            raw += message(1, row)
        game = Mock(server_id=server)
        game._public_rpc.side_effect = [message(1, '2'*32), raw]
        tables = {name:{'sha256':'a'*64, 'byteSize':123} for name in TABLES}
        return game, tables

    def test_region_version_can_differ_only_when_all_event_source_tables_match(self):
        for server in ('global-en','global-kr'):
            game, tables = self.fixture(server)
            fetch = Mock(return_value=tables)
            result = verify_shared_event_tables(game, 'host', {'contentMasterVersion':'1'*32}, fetch=fetch)
            self.assertEqual(result['targetServerId'], server)
            self.assertEqual(result['sourceMasterVersion'], '1'*32)
            self.assertEqual(result['targetMasterVersion'], '2'*32)
            self.assertEqual(fetch.call_args_list[0].args[1], '1'*32)
            self.assertEqual(fetch.call_args_list[1].args[1], '2'*32)

    def test_any_source_table_difference_blocks_before_sdk_login(self):
        for name in TABLES:
            game, tables = self.fixture('global-en')
            changed = copy.deepcopy(tables); changed[name]['sha256'] = 'b'*64
            with self.assertRaisesRegex(LoginError, '^ranking_region_event_tables_differ$'):
                verify_shared_event_tables(game, 'host', {'contentMasterVersion':'1'*32},
                                           fetch=Mock(side_effect=[tables,changed]))
        plan = {'serverId':'global-en'}
        with patch('tools.growth_login.GameClient.discover', return_value='host'), \
             patch('tools.collect_player_rankings.verify_shared_event_tables',
                   side_effect=LoginError('ranking_region_event_tables_differ')), \
             patch('tools.collect_player_rankings.SdkClient') as sdk:
            with self.assertRaisesRegex(LoginError, 'ranking_region_event_tables_differ'):
                run_capture(plan, object(), 'PRIVATE', 'PRIVATE', None, sdk_factory=sdk)
            sdk.assert_not_called()

    def test_missing_source_identity_and_unsafe_cdn_fail_closed(self):
        game, _ = self.fixture('global-kr')
        fetch = Mock()
        with self.assertRaisesRegex(LoginError, 'ranking_region_event_verification_failed'):
            verify_shared_event_tables(game, 'host', {}, fetch=fetch)
        fetch.assert_not_called()
        game, _ = self.fixture('global-kr')
        # An untrusted CDN must be refused before any HTTP fetch.
        game._public_rpc.side_effect = [message(1,'2'*32),
            message(1,message(1,'TW/HK/MO')+message(8,'2')+message(2,'https://evil.invalid/prod/hk_'+'1'*32))]
        with self.assertRaisesRegex(LoginError, 'ranking_region_event_verification_failed'):
            verify_shared_event_tables(game, 'host', {'contentMasterVersion':'1'*32}, fetch=fetch)
        fetch.assert_not_called()

    def test_manifest_identity_required_tables_and_duplicates_are_checked(self):
        version = '1'*32
        manifest = {'version':version,'files':[{'name':name,'hash':'a'*64,'size':123} for name in TABLES]}
        self.assertEqual(set(manifest_tables(manifest,version)),set(TABLES))
        for bad in ({**manifest,'version':'2'*32},
                    {**manifest,'files':manifest['files'][:-1]},
                    {**manifest,'files':manifest['files']+[manifest['files'][0]]}):
            with self.assertRaises(ValueError): manifest_tables(bad,version)


if __name__ == '__main__':
    unittest.main()
