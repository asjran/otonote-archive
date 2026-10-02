import os,tempfile,unittest,fcntl
from pathlib import Path
from tools.content_retention import cleanup_content
from tools.content_publication import write

class ContentRetentionTests(unittest.TestCase):
    def test_cleanup_skips_a_concurrent_edition_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with (root/'.publication.lock').open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=cleanup_content(root)
            self.assertEqual(result['skipped'],'publication_in_progress')
            self.assertEqual(result['removedSnapshots'],[])

    def test_jp_pointers_protect_old_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'releases').mkdir()
            for n in range(7):
                path=root/'releases'/f'{n:024x}';path.mkdir()
                write(path/'manifest.json',{'root':'/content/releases/'+path.name+'/'})
                write(path/'.receipt.json',{'files':{}});os.utime(path,(n,n))
            for prefix,n in [('current.json',0),('previous.json',1),('jp/current.json',2),('jp/previous.json',3)]:
                write(root/prefix,{'manifest':f'/content/releases/{n:024x}/manifest.json'})
            self.assertEqual(set(cleanup_content(root,now=8*86400)['removedSnapshots']),{f'{n:024x}' for n in (4,5,6)})

    def test_only_current_previous_remain_even_when_other_snapshots_are_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);releases=root/'releases';releases.mkdir()
            for n in range(6):
                name=f'{n:024x}';path=releases/name;path.mkdir()
                write(path/'manifest.json',{'root':'/content/releases/'+name+'/'})
                write(path/'.receipt.json',{'files':{}});os.utime(path,(n,n))
            write(root/'current.json',{'manifest':'/content/releases/'+f'{0:024x}'+'/manifest.json'})
            write(root/'previous.json',{'manifest':'/content/releases/'+f'{1:024x}'+'/manifest.json'})
            (releases/'operator-backup').mkdir()
            shared=releases/f'{0:024x}'/'shared.bin';shared.write_bytes(b'current media')
            os.link(shared,releases/f'{2:024x}'/'shared.bin')
            report=cleanup_content(root,now=10)
            self.assertEqual(set(report['removedSnapshots']),{f'{n:024x}' for n in (2,3,4,5)})
            self.assertEqual(shared.read_bytes(),b'current media')
            self.assertTrue((releases/f'{1:024x}').is_dir())
            self.assertTrue((releases/'operator-backup').is_dir())
            self.assertEqual(cleanup_content(root,now=10)['removedSnapshots'],[])

    def test_missing_or_broken_pointer_never_deletes_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'releases'/('a'*24);path.mkdir(parents=True)
            write(path/'manifest.json',{'root':'/content/releases/'+path.name+'/'})
            write(path/'.receipt.json',{'files':{}})
            self.assertEqual(cleanup_content(root)['skipped'],'no_current_pointer')
            write(root/'current.json',{'manifest':'/content/releases/'+('b'*24)+'/manifest.json'})
            with self.assertRaisesRegex(ValueError,'missing retention target'):cleanup_content(root)
            self.assertTrue(path.is_dir())

if __name__=='__main__':unittest.main()
