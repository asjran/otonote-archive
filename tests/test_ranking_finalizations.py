import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.collect_player_rankings import main
from tools.growth_login import LoginError
from tools.import_player_rankings import publish_final_observation
from tools.ranking_finalizations import remember_plan, pending_plan


def plan(identity='3'):
    return {'eventId':identity,'eventName':'Event '+identity,'eventStartAt':'2026-10-01T12:00:00+08:00',
            'eventEndAt':'2026-10-17T14:59:59+08:00','ttl':900,'boards':[{'type':'event-points'}],
            'uncollectedBoards':[],'contentMasterVersion':'a'*32,'contentReleaseId':'global-fixture'}


class RankingFinalizationTests(unittest.TestCase):
    def test_turnover_remembers_old_plan_even_when_new_projection_has_removed_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state';observations=root/'observations'
            remember_plan(state,plan(),'global-en')
            newer=plan('4');newer.update(eventStartAt='2026-10-18T12:00:00+08:00',eventEndAt='2026-10-26T12:00:00+08:00')
            remember_plan(state,newer,'global-en')
            self.assertEqual(pending_plan(state,observations,'global-en',now=datetime(2026,10,18,tzinfo=timezone.utc))['eventId'],'3')
            def capture(selected,profile,account,password,output,*,progress,publisher):
                self.assertEqual(selected['eventId'],'3');self.assertEqual(selected['serverId'],'global-en')
                self.assertIs(publisher,publish_final_observation)
                return publisher({'schemaVersion':1,'serverId':'global-en','observedAt':'2026-10-18T00:00:00Z',
                    'expiresAt':'2026-10-18T00:15:00Z','boards':[{'eventId':'3','eventName':'Event 3',
                    'type':'event-points','entries':[]}]},output,'global-en')
            with patch('tools.collect_player_rankings.read_ended_content_plan',return_value=None), \
                 patch('tools.collect_player_rankings.Profile.from_resources'), \
                 patch('tools.collect_player_rankings.run_capture',side_effect=capture), \
                 patch('tools.collect_player_rankings.getpass.getpass',return_value='FAKE'), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--mode','finalize','--server','global-en','--root',str(observations),
                    '--state-dir',str(state),'--sdk-resources',str(root/'sdk.xml'),'--prompt']),0)
            self.assertIsNone(pending_plan(state,observations,'global-en',now=datetime(2026,10,18,tzinfo=timezone.utc)))
            self.assertFalse((observations/'global-en/current.json').exists())

    def test_failed_final_read_leaves_plan_pending_and_never_creates_a_final_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state';observations=root/'observations'
            remember_plan(state,plan(),'global-hmt')
            with patch('tools.collect_player_rankings.read_ended_content_plan',return_value=None), \
                 patch('tools.collect_player_rankings.Profile.from_resources'), \
                 patch('tools.collect_player_rankings.run_capture',side_effect=LoginError('game_rpc_unavailable')), \
                 patch('tools.collect_player_rankings.getpass.getpass',return_value='FAKE'), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--mode','finalize','--root',str(observations),'--state-dir',str(state),
                    '--sdk-resources',str(root/'sdk.xml'),'--prompt']),2)
            self.assertEqual(pending_plan(state,observations,'global-hmt')['eventId'],'3')
            self.assertFalse((observations/'global-hmt/archive').exists())

    def test_pending_plans_are_server_scoped_and_cannot_store_raw_player_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=plan();p['serverId']='global-en'
            with self.assertRaises(ValueError):remember_plan(root,p,'global-kr')
            p=plan();p['boards'][0]['entries']=[{'name':'PRIVATE'}]
            with self.assertRaises(ValueError):remember_plan(root,p,'global-en')


if __name__=='__main__':unittest.main()
