import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from backend.admin.store import Store, window_bounds
from backend.admin.node import Jobs, run_worker, WorkflowBusy
from tools import global_update as workflow
from tools import admin_resource_workflow as manual
from tools.global_remote_sync import write_json, read_json, file_hash


class HistoryTests(unittest.TestCase):
    def test_yesterday_excludes_midnight_and_today_in_events_and_traffic(self):
        midnight=dt.datetime(2026,9,29,16,tzinfo=dt.timezone.utc).timestamp()
        site={'id':'site','timezone':'Asia/Shanghai'}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'stats.sqlite')
            for i,ts in enumerate([midnight-86401,midnight-86400,midnight-1,midnight,midnight+1]):
                store.add_event({'site':'site','id':str(i),'type':'page_view','path':'/','visitor':str(i)},'Asia/Shanghai',ts)
                with store.transaction() as db:
                    db.execute('INSERT INTO traffic VALUES(?,?,?,?,?,?,?)',('site',int(ts)//60*60,'/','page',200,1,100)) if i not in (2,4) else None
            yesterday=store.summary(site,'yesterday',midnight+100)
            self.assertEqual(yesterday['totals']['page_view'],2)
            self.assertEqual(yesterday['dailyVisitorsSum'],2)
            self.assertEqual(sum(p['views'] for p in yesterday['timeline']),2)
            self.assertEqual(yesterday['traffic'][0]['requests'],1)
            self.assertEqual(yesterday['until'],midnight)
            self.assertTrue(yesterday['historical'])
            exact=store.summary(site,'yesterday',midnight)
            self.assertEqual(exact['totals']['page_view'],2)
            self.assertTrue(exact['historical'])
            self.assertEqual(store.summary(site,'date:2026-09-29',midnight+100)['totals'],yesterday['totals'])
            self.assertEqual(store.summary(site,'today',midnight+100)['totals']['page_view'],2)
            store.close()

    def test_historical_loads_survive_raw_retention_and_exclude_next_day(self):
        now=dt.datetime(2026,9,30,4,tzinfo=dt.timezone.utc).timestamp()
        start,end=window_bounds('yesterday','Asia/Shanghai',now)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'stats.sqlite')
            for ts,rate in [(start+65,8),(end+5,99)]:
                store.add_load('source',{'ts':ts,'elapsed':5,'txMbps':rate,'txBytes':100,'active':3})
            store.prune(now)
            result=store.loads('source',now=now,window='yesterday')
            self.assertEqual(len(result['points']),1)
            self.assertEqual(result['points'][0]['txMbps'],8)
            self.assertTrue(result['points'][0]['gap'])
            self.assertTrue(result['historical'])
            self.assertEqual(result['resolution'],60)
            exact=store.loads('source',now=end,window='yesterday')
            self.assertTrue(exact['historical'])
            self.assertEqual(len(exact['points']),1)
            store.close()

    def test_calendar_validation_and_dst(self):
        now=dt.datetime(2026,9,30,4,tzinfo=dt.timezone.utc).timestamp()
        for value in ['date:2026-10-01','date:2026-08-01','date:2026-09-31','date:bad']:
            with self.assertRaises(ValueError): window_bounds(value,'Asia/Shanghai',now)
        start,end=window_bounds('yesterday','America/New_York',dt.datetime(2026,3,9,16,tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(end-start,23*3600)


class ManualStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.workspace=self.root/'workflow';self.workspace.mkdir()
        self.plan=self.root/'inputs.json'
        write_json(self.plan,{'environments':[{'masterRoot':str(self.root/'master'),'contentReleaseId':'release'}]})
        self.config={'workspace':self.workspace,'contentPublication':{'root':str(self.root/'content')},'clientVersion':'1.0.1','completeContent':True,'baseline':self.root/'baseline','inputPlan':self.plan}
        write_json(self.root/'content/current.json',{'version':'original'})
        self.build=self.workspace/'builds'/'old';self.candidate=self.build/'candidate';self.candidate.mkdir(parents=True)
        (self.candidate/'data.json').write_text('{}')
        write_json(self.candidate/'candidate.json',{'status':'candidate_generated','historicalReplay':False,'inputPlanSha256':file_hash(self.plan),'files':{'data.json':file_hash(self.candidate/'data.json')}})
        self.previous={'inputPlanSha256':file_hash(self.plan),'buildDirectory':str(self.build),'observation':{},
                       'chartProjectionFingerprint':workflow.chart_projection_fingerprint()}
        write_json(self.workspace/'state.json',self.previous)
        self.inputs={'schemaVersion':1,'inputPlan':str(self.plan),'inputPlanSha256':file_hash(self.plan),'observation':{},'package':{},'packageChanged':False}
        write_json(self.workspace/'manual-inputs.json',self.inputs)
        self.preflight=patch('tools.release_preflight.inspect_plan',return_value={'status':'passed'});self.preflight.start();self.addCleanup(self.preflight.stop)
        self.rules=patch('tools.scoring_content.bind_scoring_rules',return_value={'sourceReleaseId':'release'});self.rules.start();self.addCleanup(self.rules.stop)

    def invoke(self,action,identity=None):
        return manual.execute(self.config,workflow.Journal(self.workspace,action),action,identity)

    def test_build_is_unpublished_and_reuses_current_enriched_candidate(self):
        with patch('tools.content_publication.publish_content') as publisher:
            result=self.invoke('build');publisher.assert_not_called()
        self.assertEqual(read_json(self.workspace/'state.json'),self.previous)
        self.assertEqual(read_json(self.workspace/'manual-candidate.json')['candidate'],str(self.candidate))
        self.assertEqual(len(result['candidateId']),64)
        self.assertEqual(read_json(self.root/'content/current.json'),{'version':'original'})

    def test_fetch_only_writes_inputs_and_invalidates_manual_candidate(self):
        self.invoke('build')
        with patch.object(workflow,'doctor'),patch.object(workflow,'package_check',return_value={'package':{},'packageChanged':False}),patch.object(workflow,'update',return_value={'inputPlan':str(self.plan),'observation':{}}),patch('tools.content_publication.publish_content') as publish:
            self.invoke('fetch');publish.assert_not_called()
        self.assertFalse((self.workspace/'manual-candidate.json').exists())
        self.assertEqual(read_json(self.workspace/'state.json'),self.previous)

    def test_publish_rejects_stale_identity_baseline_and_changed_files(self):
        identity=self.invoke('build')['candidateId']
        with patch('tools.content_publication.publish_content') as publish:
            with self.assertRaisesRegex(ValueError,'candidate changed'):self.invoke('publish','a'*64)
            write_json(self.root/'content/current.json',{'version':'newer'})
            with self.assertRaisesRegex(ValueError,'published content changed'):self.invoke('publish',identity)
            publish.assert_not_called()
        identity=self.invoke('build')['candidateId']
        (self.candidate/'candidate.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'candidate changed'):self.invoke('publish',identity)

    def test_publish_failure_keeps_success_state_and_candidate_for_inspection(self):
        identity=self.invoke('build')['candidateId']
        with patch('tools.content_publication.publish_content',side_effect=ValueError('bad digest')):
            with self.assertRaisesRegex(ValueError,'bad digest'):self.invoke('publish',identity)
        self.assertEqual(read_json(self.workspace/'state.json'),self.previous)
        self.assertTrue((self.workspace/'manual-candidate.json').exists())

    def test_projection_change_after_manual_build_requires_new_candidate(self):
        identity=self.invoke('build')['candidateId']
        with patch.object(workflow,'chart_projection_fingerprint',return_value='new-model'), \
             patch('tools.content_publication.publish_content') as publish:
            with self.assertRaisesRegex(ValueError,'chart projection changed'):
                self.invoke('publish',identity)
            publish.assert_not_called()
        self.assertEqual(read_json(self.workspace/'state.json'),self.previous)

    def test_legacy_manual_candidate_is_rebuilt_without_mutating_original(self):
        previous={key:value for key,value in self.previous.items() if key!='chartProjectionFingerprint'}
        write_json(self.workspace/'state.json',previous)
        original=(self.candidate/'candidate.json').read_bytes()
        def compile_data(journal,name,args):
            self.assertEqual(name,'compile-data')
            target=Path(args[args.index('--output')+1])
            target.mkdir(parents=True)
            (target/'data.json').write_text('{}')
            write_json(target/'candidate.json',{'status':'candidate_generated','historicalReplay':False,
                'inputPlanSha256':file_hash(self.plan),'files':{'data.json':file_hash(target/'data.json')}})
        with patch.object(workflow.Journal,'command',autospec=True,side_effect=compile_data) as compile:
            self.invoke('build')
            compile.assert_called_once()
        selected=read_json(self.workspace/'manual-candidate.json')
        self.assertNotEqual(selected['candidate'],str(self.candidate))
        self.assertEqual(selected['chartProjectionFingerprint'],workflow.chart_projection_fingerprint())
        self.assertEqual((self.candidate/'candidate.json').read_bytes(),original)

    def test_success_updates_automatic_workflow_baseline(self):
        identity=self.invoke('build')['candidateId']
        with patch('tools.content_publication.publish_content',return_value={'status':'content_published'}), patch('tools.content_retention.cleanup_content') as cleanup:
            self.invoke('publish',identity)
            cleanup.assert_called_once_with(self.config['contentPublication']['root'])
        self.assertEqual(read_json(self.workspace/'state.json')['candidate'],str(self.candidate))
        self.assertFalse((self.workspace/'manual-candidate.json').exists())

    def test_shared_lock_returns_retryable_exit_without_overwriting_journal(self):
        with workflow.locked(self.workspace),patch.object(workflow,'load_config',return_value=self.config):
            self.assertEqual(workflow.main(['fetch','--config','ignored']),75)


class QueueTests(unittest.TestCase):
    def test_candidate_is_part_of_idempotency_and_busy_task_stays_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'database':str(Path(tmp)/'jobs.sqlite'),'profiles':[{'id':'global','capabilities':['publish']} ]}
            jobs=Jobs(config['database']);payload={'profile':'global','action':'publish','key':'a'*32,'candidate':'a'*64}
            first=jobs.create(payload,'owner')
            self.assertEqual(jobs.create(payload,'owner')['id'],first['id'])
            with self.assertRaises(ValueError):jobs.create({**payload,'candidate':'b'*64},'owner')
            run_worker(config,once=True,executor=Mock(side_effect=WorkflowBusy))
            self.assertEqual(jobs.list()[0]['status'],'queued')
            captured=[]
            run_worker(config,once=True,executor=lambda c,p:captured.append(p) or True)
            self.assertEqual(captured[0]['_candidate'],'a'*64)
            self.assertEqual(jobs.list()[0]['status'],'succeeded');jobs.close()


class PermissionTests(unittest.TestCase):
    def test_publish_requires_allowlisted_actor_and_exact_candidate(self):
        from fastapi.testclient import TestClient
        from backend.admin.node import create_node
        from backend.admin.app import create_admin
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'UPGRADE_READ':'r'*40,'UPGRADE_WRITE':'w'*40,'UPGRADE_PROXY':'p'*40}):
            profile={'id':'global','workspace':tmp,'capabilities':['check','fetch','build','publish'],'publishUsers':['owner']}
            node_config={'schemaVersion':1,'role':'node','port':18082,'database':tmp+'/jobs.sqlite','profiles':[profile],'readTokenEnv':'UPGRADE_READ','writeTokenEnv':'UPGRADE_WRITE'}
            with TestClient(create_node(node_config)) as client:
                payload={'profile':'global','action':'publish','actor':'reader','key':'a'*32,'candidate':'c'*64}
                headers={'Authorization':'Bearer '+'w'*40}
                self.assertEqual(client.post('/tasks',json=payload,headers=headers).status_code,403)
                payload['actor']='owner'
                self.assertEqual(client.post('/tasks',json={**payload,'candidate':'../path'},headers=headers).status_code,400)
                self.assertEqual(client.post('/tasks',json=payload,headers=headers).status_code,200)
            config={'schemaVersion':1,'role':'admin','port':18080,'origin':'http://127.0.0.1:18080','auth':{'mode':'proxy','users':['owner','reader'],'proxyTokenEnv':'UPGRADE_PROXY'},'sites':[], 'nodes':[{'id':'node','url':'http://127.0.0.1:18082','profiles':['global'],'capabilities':['check','fetch','build','publish'],'publishUsers':['owner'],'readTokenEnv':'UPGRADE_READ','writeTokenEnv':'UPGRADE_WRITE'}]}
            calls=[]
            with TestClient(create_admin(config,transport=lambda *args:calls.append(args) or {}),base_url=config['origin']) as client:
                h={'X-Admin-Proxy':'p'*40,'X-Admin-User':'reader','Origin':config['origin'],'X-OurNotes-Request':'1'}
                self.assertFalse(client.get('/api/config',headers=h).json()['nodes'][0]['canPublish'])
                body={k:v for k,v in payload.items() if k!='actor'}
                self.assertEqual(client.post('/api/nodes/node/tasks',json=body,headers=h).status_code,403)
                self.assertFalse(calls)
                self.assertEqual(client.post('/api/nodes/node/tasks',json=body,headers={**h,'X-Admin-User':'owner'}).status_code,200)
                self.assertEqual(calls[0][2]['actor'],'owner')


class ExportTests(unittest.TestCase):
    def test_export_filters_series_and_time_range(self):
        from fastapi.testclient import TestClient
        from backend.admin.app import create_admin
        config={'schemaVersion':1,'role':'admin','port':18080,'origin':'http://127.0.0.1:18080','auth':{'mode':'preview'},'sites':[{'id':'site','source':'stats','timezone':'Asia/Shanghai'}],'sources':[{'id':'stats','url':'http://127.0.0.1:18081'}]}
        with TestClient(create_admin(config,transport=lambda *args:{'timeline':[{'ts':100,'views':3,'downloads':2},{'ts':200,'views':8,'downloads':5}]}),base_url=config['origin']) as client:
            response=client.get('/api/export/site?kind=visits&fields=views&start=90&end=110')
            self.assertEqual(response.status_code,200)
            self.assertIn('attachment',response.headers['content-disposition'])
            self.assertIn('浏览量',response.text)
            self.assertNotIn('下载点击',response.text)
            self.assertEqual(len(response.text.splitlines()),2)
            self.assertEqual(client.get('/api/export/site?kind=visits&fields=arbitrary').status_code,400)
            self.assertEqual(client.get('/api/export/site?kind=visits&start=nan').status_code,400)
