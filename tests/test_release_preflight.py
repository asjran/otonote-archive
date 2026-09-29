import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_preflight import (
    CURRENT_SITE_MASTER_TABLES, PreflightError, _master_aggregate,
    check_environment, digest, inspect_plan, load_plan,
)
from tools import site_catalog


class ReleasePreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.master = self.root / 'master'
        self.master.mkdir()
        records = []
        for name in CURRENT_SITE_MASTER_TABLES:
            path = self.master / (name + '.json')
            path.write_text('{"_allData": [{"_id": 1}]}')
            records.append({'logicalName': path.name, 'sha256': digest(path)})
        self.assets = self.root / 'assets.json'
        self.assets.write_text('{"resources": []}')
        self.manifest = self.root / 'release.json'
        self.baseline = {'schemaVersion': 1, 'identity': {'region': 'global', 'channel': 'production', 'contentReleaseId': 'global-production-test'},
                         'master': {'aggregateSha256': _master_aggregate(records)},
                         'objects': {'assetManifest': {'sha256': digest(self.assets), 'byteSize': self.assets.stat().st_size}},
                         'statistics': {'criticalTableRows': {name: 1 for name in CURRENT_SITE_MASTER_TABLES}}}
        self.manifest.write_text(json.dumps(self.baseline))
        self.entry = {'id': 'global-production', 'region': 'global', 'channel': 'production', 'contentReleaseId': 'global-production-test',
                      'manifest': 'release.json', 'manifestSha256': digest(self.manifest), 'masterRoot': 'master', 'assetManifest': 'assets.json'}
        self.plan = self.root / 'plan.json'
        self.write_plan([self.entry])

    def write_plan(self, entries):
        self.plan.write_text(json.dumps({'schemaVersion': 1, 'environments': entries}))

    def test_verified_inputs_pass_without_writing_inputs(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = inspect_plan(self.plan, root=self.root)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['publicationReady'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_changed_master_fails_even_with_same_row_count(self):
        (self.master / 'MasterBand.json').write_text('{"_allData": [{"_id": 99}]}')
        result = check_environment(self.entry, self.root)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('master_digest', [c['name'] for c in result['checks'] if c['status'] == 'failed'])

    def test_relabeling_manifest_fails_pin_and_identity(self):
        self.baseline['identity']['region'] = 'retired'
        self.manifest.write_text(json.dumps(self.baseline))
        result = check_environment(self.entry, self.root)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['tableRows'], {})

    def test_correct_pin_cannot_override_expected_channel(self):
        self.baseline['identity']['channel'] = 'staging'
        self.manifest.write_text(json.dumps(self.baseline))
        self.entry['manifestSha256'] = digest(self.manifest)
        self.assertEqual(check_environment(self.entry, self.root)['status'], 'failed')

    def test_missing_formal_inputs_are_external_gate(self):
        formal = {'id': 'global-production', 'region': 'global', 'channel': 'production'}
        self.assertEqual(check_environment(formal, self.root)['status'], 'external_gate')

    def test_global_production_satisfies_formal_gate(self):
        self.assertEqual(inspect_plan(self.plan, root=self.root, require_production=True)['status'], 'passed')

    def test_asset_manifest_change_fails(self):
        self.assets.write_text('{"resources": [1]}')
        self.assertEqual(check_environment(self.entry, self.root)['status'], 'failed')

    def test_missing_and_invalid_tables_are_not_empty_success(self):
        (self.master / 'MasterBand.json').unlink()
        self.assertEqual(check_environment(self.entry, self.root)['status'], 'failed')
        (self.master / 'MasterCharacter.json').write_text('{')
        self.assertEqual(check_environment(self.entry, self.root)['status'], 'failed')

    def test_duplicate_and_unknown_environment_rejected(self):
        with self.assertRaisesRegex(PreflightError, 'unknown'):
            inspect_plan(self.plan, root=self.root, environments=['unknown-production'])
        self.write_plan([self.entry, self.entry])
        with self.assertRaisesRegex(PreflightError, 'duplicate'):
            load_plan(self.plan)

    def test_default_plan_contains_only_global_production(self):
        entries = load_plan(site_catalog.ROOT / 'config/release-inputs.json')
        self.assertEqual([entry['id'] for entry in entries], ['global-production'])
        self.assertEqual(entries[0]['region'], 'global')
        with self.assertRaisesRegex(PreflightError, 'unknown'):
            inspect_plan(site_catalog.ROOT / 'config/release-inputs.json', environments=['unlisted-production'])

    def test_local_catalog_refuses_a_different_release(self):
        with patch.object(site_catalog, 'inspect_plan', return_value={'status': 'passed'}), \
             patch.object(site_catalog, 'load_plan', return_value=[self.entry]), \
             patch.object(site_catalog, 'ROOT', self.root):
            self.root.joinpath('config').mkdir()
            with self.assertRaisesRegex(PreflightError, 'missing'):
                site_catalog.main()
