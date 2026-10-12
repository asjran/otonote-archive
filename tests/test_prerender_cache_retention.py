import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from tools import prerender_cache_retention as cache
from tools.operations import AuditError


class CacheRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.content, self.rendered = root/'content', root/'rendered'
        (self.content/'releases').mkdir(parents=True)
        (self.content/'jp').mkdir()
        (self.rendered/'releases').mkdir(parents=True)
        self.pointers = []
        for n in range(1, 7):
            rid = format(n, '024x')
            release = self.content/'releases'/rid
            release.mkdir()
            raw = json.dumps({'root': '/content/releases/'+rid+'/'}).encode()
            (release/'manifest.json').write_bytes(raw)
            (release/'data.json').write_bytes(b'{}')
            objects = {name: {'sha256': hashlib.sha256((release/name).read_bytes()).hexdigest(),
                             'bytes': (release/name).stat().st_size}
                       for name in ('manifest.json', 'data.json')}
            receipt = {'schemaVersion': 1, 'releaseId': rid, 'region': 'global',
                       'objects': objects, 'manifestSha256': objects['manifest.json']['sha256']}
            (release/cache.RECEIPT).write_text(json.dumps(receipt))
            os.utime(release, (time.time()-86400*(8-n),)*2)
            self.pointers.append({'schemaVersion': 1, 'manifest': '/content/releases/'+rid+'/manifest.json',
                                  'sha256': receipt['manifestSha256']})
        for name in ('current.json', 'jp/current.json'):
            (self.content/name).write_text(json.dumps(self.pointers[5]))
        for n, name in enumerate(('current', 'current-jp', 'previous', 'previous-jp')):
            pair = 'a'*24+'-'+format(n, '024x')
            release = self.rendered/'releases'/pair
            release.mkdir()
            # The old rollback view pins input 1; its cross-region library pins 2.
            pointer = dict(self.pointers[0], libraryPointers={'jp': self.pointers[1]})
            (release/'complete.json').write_text(json.dumps({'pair': pair, 'codeId': 'a'*24, 'pointer': pointer}))
            (release/'payload.json').write_bytes(b'old tab')
            (self.rendered/name).symlink_to('releases/'+pair)
        self.cutoff = int(time.time())-86400

    def plan(self):
        return cache.run(self.content, self.rendered, cutoff=self.cutoff)

    def test_only_unreferenced_verified_cache_is_removed(self):
        before = {p: p.read_bytes() for p in (self.rendered/'releases').rglob('*') if p.is_file()}
        plan = self.plan()
        self.assertEqual([r['release'] for r in plan['releases']], [format(n, '024x') for n in (3, 4)])
        result = cache.run(self.content, self.rendered, expected=plan)
        self.assertEqual(result['releases'], 2)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(len(list((self.content/'releases').iterdir())), 4)

    def test_changed_pointer_or_cache_invalidates_plan_before_any_delete(self):
        for kind in ('pointer', 'cache'):
            with self.subTest(kind=kind):
                plan = self.plan()
                path = self.content/('current.json' if kind == 'pointer' else 'releases/'+format(3, '024x')+'/data.json')
                original = path.read_bytes()
                path.write_bytes(json.dumps(self.pointers[2]).encode() if kind == 'pointer' else b'corrupt')
                with self.assertRaises(AuditError):
                    cache.run(self.content, self.rendered, expected=plan)
                self.assertEqual(len(list((self.content/'releases').iterdir())), 6)
                path.write_bytes(original)

    def test_symlink_and_unexpected_file_block_cleanup(self):
        release = self.content/'releases'/format(3, '024x')
        path = release/'unexpected'
        path.symlink_to(self.content/'current.json')
        os.utime(release, (time.time()-5*86400,)*2)
        with self.assertRaises(AuditError):
            self.plan()
        path.unlink()
        path.write_text('unexpected')
        os.utime(release, (time.time()-5*86400,)*2)
        with self.assertRaises(AuditError):
            self.plan()

    def test_legacy_input_without_receipt_is_preserved(self):
        (self.content/'releases'/format(3, '024x')/cache.RECEIPT).unlink()
        self.assertEqual([r['release'] for r in self.plan()['releases']], [format(4, '024x')])

    def test_each_publisher_lock_blocks_maintenance(self):
        for root, name in ((self.rendered, '.render.lock'), (self.rendered, '.r2-prerender.lock'),
                           (self.content, '.r2-materialize.lock')):
            with self.subTest(name=name), (root/name).open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(AuditError):
                    self.plan()

    def test_hardlinks_outside_removed_set_are_not_counted_as_freed(self):
        path = self.content/'releases'/format(3, '024x')/'data.json'
        os.link(path, self.content/'retained-link')
        plan = self.plan()
        all_bytes = sum(row['allocated'] for entry in plan['releases'] for row in entry['files'])
        self.assertEqual(plan['estimatedReclaimBytes'], all_bytes-path.stat().st_blocks*512)


if __name__ == '__main__':
    unittest.main()
