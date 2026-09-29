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

if __name__=='__main__':unittest.main()
