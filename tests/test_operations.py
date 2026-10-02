import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
import subprocess
import contextlib
import io
from unittest.mock import patch

from tools.operations import AuditError, apply_deduplication, plan_deduplication, task_status, plan_code_deduplication, apply_code_deduplication, main


class MaintenanceTests(unittest.TestCase):
    def payload(self, root, number, data=b'{"fixture":true}'):
        pair = ('%024x' % number) + '-' + ('a' * 24)
        release = root / 'releases' / pair
        (release / 'payloads').mkdir(parents=True)
        (release / 'complete.json').write_text(json.dumps({'pair':pair,'codeId':pair[:24]}))
        path = release / 'payloads' / (hashlib.sha256(data).hexdigest() + '.json')
        path.write_bytes(data)
        return path

    def test_lossless_idempotent_dedup_preserves_every_release_and_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a,b,c = [self.payload(root,n) for n in range(3)]
            (root/'current').symlink_to(a.parent.parent.relative_to(root))
            (root/'previous').symlink_to(b.parent.parent.relative_to(root))
            pointer = os.readlink(root/'current')
            plan = plan_deduplication(root)
            self.assertEqual(len(plan['actions']),2)
            self.assertGreater(plan['estimatedReclaimBytes'],0)
            apply_deduplication(root,plan)
            self.assertEqual(len({p.stat().st_ino for p in (a,b,c)}),1)
            self.assertEqual(os.readlink(root/'current'),pointer)
            self.assertTrue(all(p.read_bytes()==b'{"fixture":true}' for p in (a,b,c)))
            self.assertEqual(plan_deduplication(root)['actions'],[])

    def test_changed_or_forged_plan_never_mutates_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.payload(root,1);b=self.payload(root,2)
            plan=plan_deduplication(root)
            plan['actions'][0]['target']='../../outside'
            with self.assertRaisesRegex(AuditError,'plan_changed'):
                apply_deduplication(root,plan)
            self.assertNotEqual(a.stat().st_ino,b.stat().st_ino)

    def test_corrupt_content_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.payload(root,1);b=self.payload(root,2)
            b.write_bytes(b'changed')
            with self.assertRaisesRegex(AuditError,'digest_mismatch'):
                plan_deduplication(root)
            b.unlink();b.symlink_to(a)
            with self.assertRaisesRegex(AuditError,'linked_payload'):
                plan_deduplication(root)

    def test_different_permissions_are_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.payload(root,1);b=self.payload(root,2)
            a.chmod(0o644);b.chmod(0o600)
            self.assertEqual(plan_deduplication(root)['actions'],[])

    def test_invalid_receipt_is_a_sanitized_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.payload(root,1)
            for value in ([],None,'not-an-object'):
                (a.parent.parent/'complete.json').write_text(json.dumps(value))
                with self.assertRaisesRegex(AuditError,'invalid_release_receipt'):
                    plan_deduplication(root)

    @unittest.skipUnless(hasattr(os,'setxattr') or sys.platform=='darwin','extended attributes unavailable')
    def test_different_extended_attributes_are_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.payload(root,1);b=self.payload(root,2)
            key='user.ournotes-test' if sys.platform.startswith('linux') else 'com.ournotes.test'
            try:
                if hasattr(os,'setxattr'):
                    os.setxattr(a,key,b'one');os.setxattr(b,key,b'two')
                else:
                    subprocess.check_call(['/usr/bin/xattr','-w',key,'one',str(a)])
                    subprocess.check_call(['/usr/bin/xattr','-w',key,'two',str(b)])
            except OSError:
                self.skipTest('filesystem does not support test attributes')
            self.assertEqual(plan_deduplication(root)['actions'],[])

    def test_running_renderer_blocks_maintenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.payload(root,1)
            with (root/'.render.lock').open('w') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(AuditError,'render_in_progress'):
                    plan_deduplication(root)

    def test_external_hardlink_does_not_overestimate_reclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.payload(root,1);b=self.payload(root,2)
            os.link(b,root/'outside-payload-store')
            plan=plan_deduplication(root)
            self.assertEqual(plan['estimatedReclaimBytes'],0)
            apply_deduplication(root,plan)
            self.assertEqual((root/'outside-payload-store').read_bytes(),b.read_bytes())

    def test_status_report_never_echoes_private_error(self):
        result=task_status({'status':'failed','error':'password=do-not-echo /private/path'})
        self.assertNotIn('do-not-echo',json.dumps(result))
        self.assertEqual(result['reason'],'task_failed')
        self.assertEqual(task_status({'status':'failed','error':'ValueError: insufficient free disk space'})['reason'],'disk_capacity_blocked')


class CodeMaintenanceTests(unittest.TestCase):
    def release(self, root, number, extra=None):
        data = {'assets/shared.js':b'export const shared = true;', 'boot-TEST.js':('boot-' + str(number)).encode()}
        data.update(extra or {})
        files = {name:hashlib.sha256(value).hexdigest() for name,value in sorted(data.items())}
        code = hashlib.sha256(json.dumps(files,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24]
        release = root/'releases'/code
        for name,value in data.items():
            path=release/'compiled'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        (release/'code-release.json').write_text(json.dumps({'schemaVersion':1,'contentSchemaVersion':1,'codeId':code,'files':files}))
        (release/'index.html').write_text('<script src="/app/releases/'+code+'/boot-TEST.js"></script>')
        return release

    def test_code_dedup_preserves_versions_receipts_shells_and_every_byte(self):
        from tools.code_publication import verify_code
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);b=self.release(root,2)
            (root/'current').symlink_to(a.relative_to(root));(root/'previous').symlink_to(b.relative_to(root))
            before={p.relative_to(root).as_posix():p.read_bytes() for p in (root/'releases').rglob('*') if p.is_file()}
            protected={p:p.stat().st_ino for release in (a,b) for p in (release/'index.html',release/'code-release.json')}
            identities=[verify_code(path)[0] for path in (a,b)]
            plan=plan_code_deduplication(root)
            self.assertEqual(plan['operation'],'deduplicate-code-assets')
            self.assertEqual(len(plan['actions']),1)
            self.assertGreater(plan['estimatedReclaimBytes'],0)
            apply_code_deduplication(root,plan)
            self.assertEqual((a/'compiled/assets/shared.js').stat().st_ino,(b/'compiled/assets/shared.js').stat().st_ino)
            self.assertEqual(protected,{p:p.stat().st_ino for p in protected})
            self.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in (root/'releases').rglob('*') if p.is_file()})
            self.assertEqual(identities,[verify_code(path)[0] for path in (a,b)])
            self.assertEqual(os.readlink(root/'current'),a.relative_to(root).as_posix())
            self.assertEqual(os.readlink(root/'previous'),b.relative_to(root).as_posix())
            self.assertEqual(plan_code_deduplication(root)['actions'],[])

    def test_code_manifest_and_digest_corruption_fail_before_mutation(self):
        for malformed in ([],None,{'schemaVersion':2},'PRIVATE-INVALID'):
            with self.subTest(malformed=malformed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);release=self.release(root,1)
                (release/'code-release.json').write_text(json.dumps(malformed))
                with self.assertRaises(AuditError):plan_code_deduplication(root)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release=self.release(root,1);marker=release/'code-release.json'
            metadata=json.loads(marker.read_text());metadata['files']['assets/shared.js']='a'*64
            marker.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(AuditError,'code_identity_mismatch'):plan_code_deduplication(root)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release=self.release(root,1)
            (release/'compiled/assets/shared.js').write_bytes(b'corrupt')
            with self.assertRaisesRegex(AuditError,'code_asset_digest_mismatch'):plan_code_deduplication(root)

    def test_traversal_and_symlink_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release=self.release(root,1);marker=release/'code-release.json'
            metadata=json.loads(marker.read_text());metadata['files']['../../outside.js']=hashlib.sha256(b'outside').hexdigest()
            metadata['codeId']=hashlib.sha256(json.dumps(metadata['files'],separators=(',',':')).encode()).hexdigest()[:24]
            marker.write_text(json.dumps(metadata));release.rename(release.parent/metadata['codeId'])
            with self.assertRaises(AuditError):plan_code_deduplication(root)
        for target in ('compiled/assets/shared.js','compiled/assets','code-release.json'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);release=self.release(root,1);path=release/target;outside=root/'outside'
                path.rename(outside);path.symlink_to(outside)
                with self.assertRaises(AuditError):plan_code_deduplication(root)

    def test_unknown_release_is_skipped_but_owned_invalid_release_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.release(root,1);(root/'releases/unknown').mkdir()
            self.assertEqual(plan_code_deduplication(root)['skippedUnknown'],1)
            (root/'releases'/('f'*24)).mkdir()
            with self.assertRaises(AuditError):plan_code_deduplication(root)

    def test_code_lock_and_stale_plan_refuse_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);b=self.release(root,2)
            with (root/'.publication.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(AuditError,'code_publication_in_progress'):plan_code_deduplication(root)
            plan=plan_code_deduplication(root)
            (a/'verification.json').write_text('{"privateReceipt":"local-only"}')
            with self.assertRaisesRegex(AuditError,'plan_changed'):apply_code_deduplication(root,plan)
            plan=plan_code_deduplication(root);plan['actions'][0]['target']='releases/'+a.name+'/index.html'
            with self.assertRaisesRegex(AuditError,'plan_changed'):apply_code_deduplication(root,plan)
            self.assertNotEqual((a/'compiled/assets/shared.js').stat().st_ino,(b/'compiled/assets/shared.js').stat().st_ino)

    def test_code_external_links_remain_valid_and_are_not_counted_as_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);releases=sorted([self.release(root,1),self.release(root,2)])
            target=releases[1]/'compiled/assets/shared.js';os.link(target,root/'external-copy')
            plan=plan_code_deduplication(root)
            self.assertEqual(plan['estimatedReclaimBytes'],0)
            apply_code_deduplication(root,plan)
            self.assertEqual((root/'external-copy').read_bytes(),target.read_bytes())

    def test_code_permissions_and_attribute_groups_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);b=self.release(root,2)
            asset=b/'compiled/assets/shared.js';asset.chmod(0o600)
            self.assertEqual(plan_code_deduplication(root)['actions'],[])
            asset.chmod(0o644)
            with patch('tools.operations.attribute_identity',side_effect=lambda p: 'second-label' if p==asset.resolve() else 'first-label'):
                self.assertEqual(plan_code_deduplication(root)['actions'],[])

    def test_shell_integrity_records_and_compiled_receipts_are_never_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shell='<script src="/app/releases/__CODE_ID__/boot-TEST.js"></script>'
            extras={'entry-shell.json':json.dumps({'sha256':hashlib.sha256(shell.encode()).hexdigest()}).encode(),
                    'nested/index.html':b'preserved html','verification.json':b'{"fixed":"receipt"}'}
            releases=[self.release(root,n,extras) for n in (1,2)]
            protected={p:p.stat().st_ino for release in releases for p in (release/'compiled'/name for name in extras)}
            plan=plan_code_deduplication(root)
            self.assertEqual(len(plan['actions']),1)
            apply_code_deduplication(root,plan)
            self.assertEqual(protected,{p:p.stat().st_ino for p in protected})

    def test_code_cli_plan_apply_and_invalid_receipt_errors_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);self.release(root,2);plan=root/'private-plan.json'
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['dedupe-plan','--code-root',str(root),'--plan',str(plan)]),0)
            self.assertNotIn('actions',json.loads(out.getvalue()))
            self.assertEqual(plan.stat().st_mode & 0o777,0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['dedupe-apply','--code-root',str(root),'--plan',str(plan)]),0)
            (a/'code-release.json').write_text('["PRIVATE-value"]')
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(['dedupe-plan','--code-root',str(root),'--plan',str(root/'invalid-plan')]),2)
            self.assertEqual(json.loads(err.getvalue()),{'status':'blocked','reason':'invalid_code_receipt'})

    def test_partial_code_apply_is_lossless_and_can_be_reaudited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);releases=[self.release(root,n) for n in range(3)]
            plan=plan_code_deduplication(root);replace=os.replace;calls=[]
            def fail_second(source,target):
                calls.append(target)
                if len(calls)==2:raise OSError('synthetic failure')
                replace(source,target)
            with patch('tools.operations.os.replace',side_effect=fail_second):
                with self.assertRaises(OSError):apply_code_deduplication(root,plan)
            self.assertTrue(all((p/'compiled/assets/shared.js').read_bytes()==b'export const shared = true;' for p in releases))
            self.assertEqual(len(plan_code_deduplication(root)['actions']),1)
            self.assertFalse(list(root.rglob('.dedupe-*')))

    def test_explicit_exclusion_never_reads_or_changes_the_whole_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);b=self.release(root,2);excluded=self.release(root,3)
            unexpected=excluded/'compiled/unlisted.js';unexpected.write_bytes(b'untouched extra asset')
            (root/'current').symlink_to(excluded.relative_to(root))
            before={p:(p.stat().st_ino,p.read_bytes()) for p in excluded.rglob('*') if p.is_file()}
            original_open=Path.open;original_stat=Path.stat
            def guard_open(path,*args,**kwargs):
                if path==excluded or excluded in path.parents:raise AssertionError('excluded version was opened')
                return original_open(path,*args,**kwargs)
            def guard_stat(path,*args,**kwargs):
                if path==excluded or excluded in path.parents:raise AssertionError('excluded version was inspected')
                return original_stat(path,*args,**kwargs)
            with patch.object(Path,'open',guard_open),patch.object(Path,'stat',guard_stat):
                plan=plan_code_deduplication(root,[excluded.name])
                self.assertEqual(plan['excludedCodeIds'],[excluded.name])
                self.assertEqual(len(plan['actions']),1)
                self.assertTrue(all(excluded.name not in action['source']+action['target'] for action in plan['actions']))
                apply_code_deduplication(root,plan,[excluded.name])
            self.assertEqual(before,{p:(p.stat().st_ino,p.read_bytes()) for p in before})
            self.assertEqual(os.readlink(root/'current'),excluded.relative_to(root).as_posix())
            self.assertEqual((a/'compiled/assets/shared.js').stat().st_ino,(b/'compiled/assets/shared.js').stat().st_ino)

    def test_exclusion_does_not_relax_other_release_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);excluded=self.release(root,2)
            (excluded/'code-release.json').write_text('invalid excluded receipt')
            (a/'compiled/unlisted.js').write_bytes(b'unlisted')
            with self.assertRaisesRegex(AuditError,'code_inventory_mismatch'):
                plan_code_deduplication(root,[excluded.name])
            (a/'compiled/unlisted.js').unlink()
            (a/'compiled/assets/shared.js').write_bytes(b'corrupt')
            with self.assertRaisesRegex(AuditError,'code_asset_digest_mismatch'):
                plan_code_deduplication(root,[excluded.name])

    def test_apply_requires_the_same_explicit_exclusions_and_untampered_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.release(root,1);b=self.release(root,2);excluded=self.release(root,3)
            plan=plan_code_deduplication(root,[excluded.name])
            for supplied in ((),[a.name],[excluded.name,a.name]):
                with self.assertRaisesRegex(AuditError,'plan_changed'):
                    apply_code_deduplication(root,plan,supplied)
            altered=dict(plan,excludedCodeIds=[a.name])
            with self.assertRaisesRegex(AuditError,'plan_changed'):
                apply_code_deduplication(root,altered,[a.name])
            self.assertNotEqual((a/'compiled/assets/shared.js').stat().st_ino,(b/'compiled/assets/shared.js').stat().st_ino)

    def test_exclusion_ids_are_strict_and_legacy_plans_still_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.release(root,1);self.release(root,2)
            for invalid in ('F'*24,'f'*23,'f'*25,'../'+'f'*24,'f'*24+'\n',None,24):
                with self.subTest(invalid=invalid),self.assertRaisesRegex(AuditError,'invalid_excluded_code_id'):
                    plan_code_deduplication(root,[invalid])
            legacy=plan_code_deduplication(root)
            self.assertNotIn('excludedCodeIds',legacy)
            apply_code_deduplication(root,legacy)

    def test_cli_repeats_exclusions_and_rejects_them_for_render_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.release(root,1);self.release(root,2);a=self.release(root,3);b=self.release(root,4)
            plan=root/'private-plan.json'; exclusions=['--exclude-code-id',b.name,'--exclude-code-id',a.name]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['dedupe-plan','--code-root',str(root),'--plan',str(plan)]+exclusions),0)
                self.assertEqual(main(['dedupe-apply','--code-root',str(root),'--plan',str(plan)]+exclusions),0)
            self.assertEqual(json.loads(plan.read_text())['excludedCodeIds'],sorted([a.name,b.name]))
            for command in ('dedupe-plan','dedupe-apply'):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(main([command,'--rendered-root',str(root),'--plan',str(plan)]+exclusions),2)
                self.assertEqual(json.loads(err.getvalue())['reason'],'code_exclusions_require_code_root')

if __name__=='__main__':
    unittest.main()
