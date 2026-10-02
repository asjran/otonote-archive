import hashlib,json,tempfile,unittest
from pathlib import Path
from tools.code_publication import publish_code
from tools.content_publication import write

class CodePublicationTests(unittest.TestCase):
    def test_code_switch_is_independent_of_content_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=root/'code';content=root/'content';write(content/'current.json',{'untouched':True})
            def source(name,code):
                src=root/name;(src/'compiled').mkdir(parents=True)
                (src/'compiled/boot-TEST.js').write_text(code)
                files={'boot-TEST.js':hashlib.sha256(code.encode()).hexdigest()}
                identity=hashlib.sha256(json.dumps(files,separators=(',',':')).encode()).hexdigest()[:24]
                write(src/'code-release.json',{'schemaVersion':1,'contentSchemaVersion':1,'codeId':identity,'files':files})
                (src/'index.html').write_text('<script src="/app/releases/'+identity+'/boot-TEST.js"></script>')
                return src
            a,b=source('a','one'),source('b','two')
            first=publish_code(a,store);second=publish_code(b,store)
            self.assertEqual((store/'previous').resolve().name,first['codeId'])
            self.assertEqual((store/'current').resolve().name,second['codeId'])
            self.assertEqual(json.loads((content/'current.json').read_text()),{'untouched':True})
            import shutil
            incoming=store/'incoming'/first['codeId'];shutil.copytree(a,incoming)
            self.assertEqual(publish_code(incoming,store)['codeId'],first['codeId'])
            publish_code(b,store)
            (b/'compiled/boot-TEST.js').write_text('corrupt')
            with self.assertRaisesRegex(ValueError,'inventory'):publish_code(b,store)
            self.assertEqual((store/'current').resolve().name,second['codeId'])
            (a/'credentials.secret').write_text('unexpected')
            with self.assertRaisesRegex(ValueError,'inventory'):publish_code(a,store)


class PublicationGuardTests(unittest.TestCase):
    def test_stale_pointer_health_rollback_and_lock(self):
        import fcntl
        from tests.test_release_candidate import candidate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=root/'store'
            a,sha=candidate(root/'a');first=publish_code(a,store,require_verified=True,expected_receipt_sha256=sha,expected_current='none')
            old=(store/'current').readlink()
            with self.assertRaisesRegex(ValueError,'current code changed'):
                publish_code(a,store,expected_current='f'*24)
            # A distinct legacy fixture isolates switch/rollback behavior from provenance.
            b=root/'b';(b/'compiled').mkdir(parents=True);(b/'compiled/boot-TEST.js').write_text('two')
            files={'boot-TEST.js':hashlib.sha256(b'two').hexdigest()};identity=hashlib.sha256(json.dumps(files,separators=(',',':')).encode()).hexdigest()[:24]
            write(b/'code-release.json',{'schemaVersion':1,'contentSchemaVersion':1,'codeId':identity,'files':files})
            (b/'index.html').write_text('<script src="/app/releases/'+identity+'/boot-TEST.js"></script>')
            with self.assertRaisesRegex(ValueError,'previous pointers restored'):
                publish_code(b,store,expected_current=first['codeId'],health_check=lambda _:False)
            self.assertEqual((store/'current').readlink(),old);self.assertFalse((store/'previous').is_symlink())
            with (store/'.publication.lock').open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):publish_code(b,store)
            self.assertEqual((store/'current').readlink(),old)

if __name__=='__main__':unittest.main()
