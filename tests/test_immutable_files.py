import tempfile
from pathlib import Path
import unittest
from tools.immutable_files import deduplicate_tree
from tools.global_remote_sync import file_hash


class DeduplicationTests(unittest.TestCase):
    def test_reuses_only_equal_bytes_and_preserves_unique_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source';source.write_bytes(b'same')
            tree=root/'tree';tree.mkdir();(tree/'a').write_bytes(b'same');(tree/'b').write_bytes(b'else')
            before={p.name:file_hash(p) for p in tree.iterdir()}
            self.assertEqual(deduplicate_tree(tree,[(source,file_hash(source))]),4)
            self.assertEqual((tree/'a').stat().st_ino,source.stat().st_ino)
            self.assertEqual(before,{p.name:file_hash(p) for p in tree.iterdir()})
