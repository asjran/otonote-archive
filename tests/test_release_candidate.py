import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.release_candidate import GATES, canonical, check_source_files, digest, inspect_source, validate_receipt
from tools.code_publication import verify_code


def candidate(root, run_id="c"*32):
    root.mkdir(); (root/'compiled').mkdir()
    (root/'compiled/boot-TEST.js').write_text('export {};')
    shell='<script src="/app/releases/__CODE_ID__/boot-TEST.js"></script>'
    (root/'compiled/entry-shell.json').write_bytes(canonical({'sha256':digest(shell.encode())}))
    source_files={'site/package-lock.json':digest(b'lock')}
    origin={'commit':'a'*40,'tree':'b'*40,'dirty':False,'files':source_files,
            'fingerprint':digest(canonical(source_files)),'lockSha256':source_files['site/package-lock.json']}
    (root/'compiled/build-source.json').write_bytes(canonical({'fingerprint':origin['fingerprint'],'commit':origin['commit'],'verificationRun':run_id}))
    files={p.name:digest(p.read_bytes()) for p in sorted((root/'compiled').iterdir())}
    code_id=digest(json.dumps(files,separators=(',',':')).encode())[:24]
    metadata={'schemaVersion':1,'contentSchemaVersion':1,'codeId':code_id,'files':files,
              'provenance':{'kind':'verified-commit','source':origin,'verificationRun':run_id}}
    (root/'index.html').write_text(shell.replace('__CODE_ID__',code_id))
    (root/'code-release.json').write_bytes(canonical(metadata))
    commands={'dependencies':['npm','ci','--ignore-scripts','--no-audit','--no-fund'],**GATES,
              'build':['node','tools/build_web_client.mjs','output/candidate']}
    receipt={'schemaVersion':1,'sourceFingerprint':origin['fingerprint'],
             'commands':[{'gate':name,'command':command,'exitCode':0,'stdoutSha256':digest(b'ok'),'stderrSha256':digest(b'')} for name,command in commands.items()],
             'artifact':{'codeId':code_id,'manifestSha256':digest((root/'code-release.json').read_bytes()),'shellSha256':digest((root/'index.html').read_bytes())}}
    (root/'verification.json').write_bytes(canonical(receipt))
    return root,digest((root/'verification.json').read_bytes())


class ReleaseCandidateTests(unittest.TestCase):
    def test_reverification_of_same_source_has_independent_release_identity(self):
        from tools.code_publication import publish_code
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a,sha_a=candidate(root/'a','c'*32);b,sha_b=candidate(root/'b','d'*32)
            first=publish_code(a,root/'store',require_verified=True,expected_receipt_sha256=sha_a,expected_current='none')
            second=publish_code(b,root/'store',require_verified=True,expected_receipt_sha256=sha_b,expected_current=first['codeId'])
            self.assertNotEqual(first['codeId'],second['codeId'])
            self.assertEqual((root/'store/previous').resolve().name,first['codeId'])

    def test_receipt_is_bound_to_source_and_exact_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,expected=candidate(Path(tmp)/'candidate')
            verify_code(root,require_verified=True,expected_receipt_sha256=expected)
            receipt=json.loads((root/'verification.json').read_text());receipt['commands'][0]['exitCode']=1
            (root/'verification.json').write_bytes(canonical(receipt))
            with self.assertRaisesRegex(ValueError,'receipt digest'):verify_code(root,expected_receipt_sha256=expected)
            with self.assertRaisesRegex(ValueError,'execution record'):verify_code(root,require_verified=True)

    def test_passed_boolean_does_not_replace_executed_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,_=candidate(Path(tmp)/'candidate')
            receipt=json.loads((root/'verification.json').read_text());receipt['commands']=[];receipt['passed']=True
            (root/'verification.json').write_bytes(canonical(receipt))
            with self.assertRaisesRegex(ValueError,'missing verification gates'):verify_code(root,require_verified=True)

    def test_shell_and_config_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,_=candidate(Path(tmp)/'candidate');shell=(root/'index.html').read_text()
            (root/'index.html').write_text(shell+'<script>alert(1)</script>')
            with self.assertRaisesRegex(ValueError,'shell digest'):verify_code(root)
            (root/'index.html').write_text(shell);(root/'private.env').write_text('SAMPLE=not-real')
            with self.assertRaisesRegex(ValueError,'inventory'):verify_code(root)

    def test_source_edit_after_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'source.mjs').write_text('one')
            source={'files':{'source.mjs':digest(b'one')}};check_source_files(root,source)
            (root/'source.mjs').write_text('two')
            with self.assertRaisesRegex(ValueError,'source changed'):check_source_files(root,source)

    def test_git_source_must_be_clean_and_match_requested_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def git(*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
            git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
            (root/'site').mkdir();(root/'site/package-lock.json').write_text('{}')
            git('add','.');git('commit','-qm','fixture')
            clean=inspect_source(root,'HEAD');self.assertFalse(clean['dirty'])
            (root/'site/package-lock.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'clean checkout'):inspect_source(root,'HEAD')
            git('update-index','--skip-worktree','site/package-lock.json')
            with self.assertRaisesRegex(ValueError,'source bytes'):inspect_source(root,'HEAD')

    def test_private_deploy_config_permissions_and_location(self):
        from tools.deploy_code import load_config
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'deploy.json';p.write_text('{}');p.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'owner-only'):load_config(p)
            p.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'missing or unknown'):load_config(p)

    def test_remote_runtime_is_verified_before_isolated_import(self):
        from tools.deploy_code import deploy,RUNTIME_BOOTSTRAP
        with tempfile.TemporaryDirectory() as tmp:
            root,expected=candidate(Path(tmp)/'candidate')
            identity=json.loads((root/'code-release.json').read_text())['codeId']
            config={'sshHost':'fixture-host','runtimeRoot':'/fixture/runtime','runtimeSha256':'f'*64,
                    'python':'/usr/bin/python3','codeRoot':'/fixture/code',
                    'healthUrl':'https://fixture.invalid/health','healthContains':'{codeId}'}
            calls=[]
            def runner(command,**options):
                calls.append((command,options))
                return canonical({'status':'code_published','codeId':identity}) if '-c' in command[-1] else b''
            with patch('tools.deploy_code.run',side_effect=runner):
                self.assertEqual(deploy(root,config,expected,'none')['status'],'code_published')
            self.assertEqual(calls[0][1]['input_data'],RUNTIME_BOOTSTRAP.encode())
            self.assertIn(' -I - ',calls[0][0][-1])
            self.assertIn(' -I -B -c ',calls[-1][0][-1])
            self.assertNotIn('PYTHONPATH=',calls[-1][0][-1])


if __name__=='__main__':unittest.main()
