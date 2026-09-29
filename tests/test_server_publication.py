import tempfile
import unittest
from pathlib import Path
from tools.global_remote_sync import file_hash, write_json, read_json
from tools.server_publication import publish


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'web'
        self.old = self.root / 'releases/old'
        (self.old / 'anontokyo').mkdir(parents=True)
        (self.old / 'anontokyo/index.html').write_text('independent product')
        (self.root / 'current').symlink_to('releases/old')
        self.site = Path(self.tmp.name) / 'site'
        self.site.mkdir(mode=0o700)
        (self.site / 'index.html').write_text('new global')
        self.receipt = Path(self.tmp.name) / 'bundle.json'
        write_json(self.receipt, {'validation': {'status': 'passed'}, 'files': {'index.html': file_hash(self.site / 'index.html')}})

    def test_publish_preserves_other_product_and_previous(self):
        result = publish(self.site, self.receipt, self.root, 'test.invalid', health=lambda _: None)
        self.assertEqual(result['status'], 'published')
        self.assertEqual((self.root / 'current').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root / 'previous').resolve(), self.old)
        self.assertEqual((self.root / 'current/anontokyo/index.html').read_text(), 'independent product')
        self.assertEqual(publish(self.site, self.receipt, self.root, 'test.invalid', health=lambda _: None)['status'], 'already_published')

    def test_health_failure_rolls_back_and_allows_retry(self):
        def fail(_): raise ValueError('unhealthy')
        with self.assertRaisesRegex(ValueError, 'unhealthy'):
            publish(self.site, self.receipt, self.root, 'test.invalid', health=fail)
        self.assertEqual((self.root / 'current').resolve(), self.old)
        self.assertFalse((self.root / 'last-auto-update.json').exists())
        self.assertEqual(publish(self.site, self.receipt, self.root, 'test.invalid', health=lambda _: None)['status'], 'published')

    def test_tampering_never_switches_current(self):
        (self.site / 'index.html').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            publish(self.site, self.receipt, self.root, 'test.invalid', health=lambda _: None)
        self.assertEqual((self.root / 'current').resolve(), self.old)

    def test_overlap_of_separate_product_fails_closed(self):
        (self.site / 'anontokyo').mkdir()
        (self.site / 'anontokyo/index.html').write_text('unexpected overwrite')
        write_json(self.receipt, {'validation': {'status': 'passed'}, 'files': {str(p.relative_to(self.site)): file_hash(p) for p in self.site.rglob('*') if p.is_file()}})
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            publish(self.site, self.receipt, self.root, 'test.invalid', health=lambda _: None)
        self.assertEqual((self.root / 'current').resolve(), self.old)
