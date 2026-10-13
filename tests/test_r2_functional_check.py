import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tools.r2_functional_check import check, DOCUMENTS

class FunctionalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'releases' / ('a' * 24);self.release.mkdir(parents=True)
        self.docs = [
            {'release': {'id': 'source'}, 'memberCards': [1], 'supportCards': [2], 'musicTracks': [3]},
            {'sourceReleaseId': 'source', 'events': {'records': []}},
            {'sourceReleaseId': 'source', 'skills': [1]},
            {'sourceReleaseId': 'source', 'verificationStatus': 'reference_compatible'},
            {'sourceReleaseId': 'source', 'status': 'compatible', 'checks': 5, 'issues': []}]
        self.write()

    def write(self):
        manifest = {'schemaVersion': 1, 'region': 'jp', 'contentReleaseId': 'source',
                    'root': '/content/releases/' + 'a' * 24 + '/', 'locales': {}}
        for locale in ('en', 'zh-CN'):
            files = {}
            for name, source in zip(DOCUMENTS, self.docs):
                doc = copy.deepcopy(source)
                if name == DOCUMENTS[0]:
                    doc['projectionContext'] = {'contentReleaseId': 'source', 'region': 'jp', 'channel': 'production', 'locale': locale}
                relative = locale + '/' + name
                target = self.release / relative;target.parent.mkdir(parents=True, exist_ok=True)
                raw = json.dumps(doc).encode();target.write_bytes(raw)
                files[name] = {'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            manifest['locales'][locale] = {'files': files}
        raw = json.dumps(manifest).encode();(self.release / 'manifest.json').write_bytes(raw)
        (self.root / 'jp').mkdir(exist_ok=True)
        (self.root / 'jp/current.json').write_text(json.dumps({'manifest': manifest['root'] + 'manifest.json', 'sha256': hashlib.sha256(raw).hexdigest(), 'contentReleaseId': 'source'}))

    def test_optional_scoring_degradation_does_not_block_new_catalog(self):
        self.docs[-1] = {'status': 'unavailable', 'issues': [{'message': 'not supported'}]}
        self.docs[-2]['verificationStatus'] = 'unavailable'
        self.write()
        result = check(self.root, 'jp')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['locales']['en']['scoring'], 'unavailable')
        self.assertIs(result['locales']['en']['gameplayVerified'], False)

    def test_cross_release_or_locale_damage_fails_before_upload(self):
        self.docs[2]['sourceReleaseId'] = 'wrong';self.write()
        with self.assertRaisesRegex(ValueError, 'release mismatch'):check(self.root, 'jp')
        self.docs[2]['sourceReleaseId'] = 'source';self.write()
        (self.release / 'en/projection/catalog.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):check(self.root, 'jp')

    def test_empty_success_and_missing_required_capability_rejected(self):
        self.docs[-1]['checks'] = 0;self.write()
        with self.assertRaisesRegex(ValueError, 'scoring success'):check(self.root, 'jp')
        self.docs[-1]['checks'] = 5;self.docs[0]['memberCards'] = [];self.write()
        with self.assertRaisesRegex(ValueError, 'capability absent'):check(self.root, 'jp')
