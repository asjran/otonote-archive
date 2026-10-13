import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import r2_state as state
from tests.test_r2_state import FakePrivateBucket


class CheckpointHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve();(self.root / 'data').mkdir()
        self.source = self.root / 'data/a';self.source.write_bytes(b'content')
        os.link(self.source, self.root / 'data/b')
        (self.root / 'data/c').write_bytes(b'content')
        self.bucket = FakePrivateBucket()

    def test_two_byte_hash_phases_preserve_aliases_and_independent_copies(self):
        with patch.object(state, 'hash_file', wraps=state.hash_file) as hashing:
            result = state.checkpoint(self.bucket, self.root, 'global', ['data'], 'none')
        self.assertEqual(hashing.call_count, 4, 'two physical files must be rehashed in each of two phases')
        pointer, _, _ = state._pointer(self.bucket, 'global')
        manifest = self.bucket.read_manifest(pointer['manifest'])[0]
        self.assertIn(b'"hardlinkTo":"data/a"', manifest)
        self.assertEqual(result['checkpointMetrics']['uniqueObjects'], 1)
        for prefix in ('inventory', 'sourceVerify'):
            self.assertEqual(result['checkpointMetrics'][prefix+'HashCalls'], 2)
            self.assertEqual(result['checkpointMetrics'][prefix+'HashBytes'], 14)

    def test_mutation_after_first_alias_hash_is_rejected_even_with_restored_mtime(self):
        original = state.hash_file
        stamp = self.source.stat()
        def mutate(path):
            value = original(path)
            if path == self.source:
                path.write_bytes(b'changed')
                os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            return value
        with patch.object(state, 'hash_file', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                state.checkpoint(self.bucket, self.root, 'global', ['data'], 'none')
        self.assertNotIn(state.pointer_key('global'), self.bucket.objects)

    def test_replacing_hardlink_with_equal_bytes_during_remote_transfer_is_rejected(self):
        original = self.bucket.put_file_new
        def replace(*args):
            result = original(*args)
            alias = self.root / 'data/b';alias.unlink();alias.write_bytes(b'content')
            return result
        self.bucket.put_file_new = replace
        with self.assertRaisesRegex(ValueError, 'hard-linked checkpoint source changed'):
            state.checkpoint(self.bucket, self.root, 'global', ['data'], 'none')
        self.assertNotIn(state.pointer_key('global'), self.bucket.objects)

    def test_inode_cache_never_crosses_phases_or_runs(self):
        first = state.checkpoint(self.bucket, self.root, 'global', ['data'], 'none')
        self.source.write_bytes(b'newdata')
        second = state.checkpoint(self.bucket, self.root, 'global', ['data'], first['pointerSha256'])
        self.assertNotEqual(first['manifestSha256'], second['manifestSha256'])
        self.assertEqual(second['uploaded'], 1)

    def test_mutation_of_an_earlier_inode_while_hashing_another_is_rejected(self):
        original = state.hash_file
        def mutate(path):
            result = original(path)
            if path.name == 'c':
                self.source.write_bytes(b'changed')
            return result
        with patch.object(state, 'hash_file', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                state.checkpoint(self.bucket, self.root, 'global', ['data'], 'none')
        self.assertNotIn(state.pointer_key('global'), self.bucket.objects)
