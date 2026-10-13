import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import update_health as health
from deploy.admin.export_ranking_health import export as export_ranking
from tools import r2_run_record as records
from backend.admin.update_health import read_health
from tests.test_r2_content import MemoryBucket

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1791876000
        self.observed = {'conditions': [], 'runs': {}, 'versions': {}, 'diskFreeBytes': 5000, 'diskRequiredBytes': 4000}

    def test_duration_dedup_recovery(self):
        self.observed['conditions'] = [{'id': 'jp:run_failed', 'region': 'jp', 'code': 'run_failed', 'grace': 900}]
        first, log = health.advance(self.observed, {}, self.now)
        self.assertEqual(first['status'], 'waiting');self.assertEqual(log, [])
        firing, log = health.advance(self.observed, first, self.now + 901)
        self.assertEqual(firing['status'], 'attention');self.assertEqual(log[0]['transition'], 'opened')
        repeated, log = health.advance(self.observed, firing, self.now + 1200)
        self.assertEqual(log, [])
        self.observed['conditions'] = []
        recovered, log = health.advance(self.observed, repeated, self.now + 1300)
        self.assertEqual(recovered['status'], 'healthy');self.assertEqual(log[0]['transition'], 'recovered')
        self.assertEqual(len(recovered['history']), 2)

    def test_private_view_rejects_stale_future_and_invalid_data_and_strips_secrets(self):
        report, _ = health.advance(self.observed, {}, self.now)
        report['secret'] = 'never-display'
        path = self.root / 'update-health.json'
        health.write_atomic(path, report)
        with patch('backend.admin.update_health.time.time', return_value=self.now):
            self.assertEqual(read_health(self.root)['status'], 'healthy')
            self.assertNotIn('never-display', json.dumps(read_health(self.root)))
        for clock in (self.now + 361, self.now - 61):
            with patch('backend.admin.update_health.time.time', return_value=clock):
                self.assertEqual(read_health(self.root), {'status': 'unavailable'})
        report['alerts'] = [{'code': 'private-value', 'region': 'jp'}]
        health.write_atomic(path, report)
        with patch('backend.admin.update_health.time.time', return_value=self.now):
            self.assertEqual(read_health(self.root), {'status': 'unavailable'})

    def test_running_grace_and_release_lag_are_separate(self):
        bucket = MemoryBucket()
        stamp = dt.datetime.fromtimestamp(self.now - 4000, dt.timezone.utc)
        for region in ('global', 'jp'):
            records.publish(bucket, region, 1, 1, 'a' * 40, 'running' if region == 'jp' else 'success', {}, now=stamp)
            pointer = {'schemaVersion': 1, 'manifest': '/content/releases/' + 'a' * 24 + '/manifest.json', 'sha256': 'b' * 64}
            bucket.put_new('content/current.json' if region == 'global' else 'content/jp/current.json', json.dumps(pointer).encode())
        ranking = self.root / 'ranking.json'
        ranking.write_text(json.dumps({'status': 'complete', 'observedAt': dt.datetime.fromtimestamp(self.now, dt.timezone.utc).isoformat()}))
        with patch('tools.update_health.read_json', side_effect=lambda path, *_: json.loads(Path(path).read_text())):
            result = health.sample(bucket, self.root / 'missing', ranking, self.root, 1, self.now)
        codes = {c['id'] for c in result['conditions']}
        self.assertIn('global:poll_stale', codes)
        self.assertNotIn('jp:poll_stale', codes)
        self.assertNotIn('jp:run_stuck', codes)
        self.assertIn('all:delivery_unknown', codes)
        self.assertIn('jp:delivery_lag', codes)
        self.assertNotIn('all:ranking_stale', codes)

    def test_retry_start_does_not_claim_recovery_before_success(self):
        bucket = MemoryBucket()
        stamp = dt.datetime.fromtimestamp(self.now, dt.timezone.utc)
        records.publish(bucket, 'jp', 1, 1, 'a' * 40, 'failure', {'restore': {'outcome': 'failure'}}, now=stamp)
        records.publish(bucket, 'jp', 2, 1, 'a' * 40, 'running', {}, now=stamp)
        result = health.sample(bucket, self.root / 'absent', self.root / 'absent', self.root, 1, self.now)
        self.assertIn('jp:run_failed', {c['id'] for c in result['conditions']})
        self.assertEqual(result['runs']['jp']['failedStage'], 'restore')

    def test_ranking_export_is_whitelisted_and_replaces_broken_success(self):
        source = self.root / 'capture.json';target = self.root / 'export.json'
        source.write_text(json.dumps({'status': 'complete', 'paused': False, 'observedAt': '2026-10-13T07:25:00Z', 'account': 'private'}))
        export_ranking(source, target)
        self.assertEqual(set(json.loads(target.read_text())), {'status', 'paused', 'observedAt'})
        source.write_text('')
        export_ranking(source, target)
        self.assertEqual(json.loads(target.read_text()), {'status': 'unavailable'})

    def test_sampling_cannot_wait_for_long_running_publication_units(self):
        unit = Path(__file__).resolve().parents[1] / 'deploy/admin/ournotes-update-health.service'
        relationships = [line for line in unit.read_text().splitlines() if line.startswith(('After=', 'Requires=', 'Wants='))]
        self.assertFalse(any('prerender' in line or 'delivery-state' in line for line in relationships))

    def test_recent_manual_success_does_not_mask_a_stale_native_schedule(self):
        bucket = MemoryBucket()
        old = dt.datetime.fromtimestamp(self.now-7200, dt.timezone.utc)
        current = dt.datetime.fromtimestamp(self.now, dt.timezone.utc)
        records.publish(bucket, 'jp', 1, 1, 'a'*40, 'success', {}, now=old, event='schedule')
        records.publish(bucket, 'jp', 2, 1, 'a'*40, 'success', {}, now=current, event='workflow_dispatch')
        result = health.sample(bucket, self.root/'missing', self.root/'missing', self.root, 1, self.now)
        codes = {item['id'] for item in result['conditions']}
        self.assertIn('jp:schedule_stale', codes)
        self.assertNotIn('jp:poll_stale', codes)
