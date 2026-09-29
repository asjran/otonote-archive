import os,tempfile,unittest
from pathlib import Path
from tools.content_retention import cleanup_content
from tools.content_publication import write

class ContentRetentionTests(unittest.TestCase):
    def test_only_old_owned_unprotected_snapshots_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);releases=root/'releases';releases.mkdir()
            for n in range(6):
                name=f'{n:024x}';path=releases/name;path.mkdir()
                write(path/'manifest.json',{'root':'/content/releases/'+name+'/'})
                write(path/'.receipt.json',{'files':{}});os.utime(path,(n,n))
            write(root/'current.json',{'manifest':'/content/releases/'+f'{0:024x}'+'/manifest.json'})
            write(root/'previous.json',{'manifest':'/content/releases/'+f'{1:024x}'+'/manifest.json'})
            (releases/'operator-backup').mkdir()
            self.assertEqual(cleanup_content(root,now=10)['removedSnapshots'],[])
            report=cleanup_content(root,now=8*86400)
            self.assertEqual(report['removedSnapshots'],[f'{2:024x}'])
            self.assertTrue((releases/'operator-backup').is_dir())

if __name__=='__main__':unittest.main()
