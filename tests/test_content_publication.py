import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import errno
import hashlib
from types import SimpleNamespace
from tools.content_publication import MEDIA_GROUPS, inventory, publish_content, rollback_content, write


class ContentPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=self.root/'content'

    def candidate(self, release='test-1', missing=False):
        candidate=self.root/release;bound=candidate/'global'/release
        for group in MEDIA_GROUPS:
            (bound/'public'/group).mkdir(parents=True)
        for group in ('growth','system-banners','mission-rewards'): write(bound/'public'/group/'manifest.json',{})
        (bound/'public/media/icon.webp').write_bytes(b'image')
        for name in ('live2d-catalog.json','immersive-scenes.json','auto-stage-skin.json'): write(bound/'supplemental-data'/name,{})
        for locale in ('en','zh-CN'):
            write(bound/'generated/releases'/release/locale/'catalog.json',{
                'projectionContext':{'contentReleaseId':release,'region':'global','channel':'production','locale':locale},
                'image':'/media/missing.webp' if missing else '/media/icon.webp'})
        write(candidate/'candidate.json',{'status':'candidate_generated','historicalReplay':False,
            'regions':[{'region':'global','channel':'production','contentReleaseId':release,'path':'global/'+release,
                        'projections':[{'locale':'zh-CN'},{'locale':'en'}]}], 'files':inventory(candidate)})
        return candidate

    def test_increment_rewrites_resources_and_preserves_previous(self):
        first=publish_content(self.candidate(),self.store)
        old=(self.store/'current.json').read_bytes()
        second=publish_content(self.candidate('test-2'),self.store)
        self.assertNotEqual(first['pointer'],second['pointer'])
        self.assertEqual((self.store/'previous.json').read_bytes(),old)
        self.assertTrue(Path(first['snapshot']).is_dir())
        catalog=json.loads((Path(second['snapshot'])/'zh-CN/catalog.json').read_text())
        self.assertTrue(catalog['image'].startswith('/content/releases/'))
        self.assertEqual(publish_content(self.root/'test-2',self.store)['status'],'unchanged')
        rollback_content(self.store)
        self.assertEqual(json.loads((self.store/'current.json').read_text()),first['pointer'])

    def test_missing_resource_and_corrupt_candidate_preserve_pointer(self):
        publish_content(self.candidate(),self.store);old=(self.store/'current.json').read_bytes()
        broken=self.candidate('missing',missing=True)
        with self.assertRaisesRegex(ValueError,'missing content reference'): publish_content(broken,self.store)
        self.assertEqual((self.store/'current.json').read_bytes(),old)
        (broken/'global/missing/public/media/icon.webp').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'inventory'): publish_content(broken,self.store)
        self.assertEqual((self.store/'current.json').read_bytes(),old)

    def test_scoring_artifact_is_version_bound_and_changes_snapshot_identity(self):
        candidate=self.candidate(); initial=publish_content(candidate,self.store)
        path=self.root/'rules.json'
        write(path,{'sourceReleaseId':'wrong','verificationStatus':'unavailable'})
        with self.assertRaisesRegex(ValueError,'scoring rules content release mismatch'):
            publish_content(candidate,self.store,scoring_rules=path)
        self.assertEqual(json.loads((self.store/'current.json').read_text()),initial['pointer'])
        rules={'sourceReleaseId':'test-1','verificationStatus':'unavailable','reason':'test'}
        write(path,rules); result=publish_content(candidate,self.store,scoring_rules=path)
        self.assertNotEqual(initial['pointer'],result['pointer'])
        manifest=json.loads((Path(result['snapshot'])/'manifest.json').read_text())
        for locale in ('en','zh-CN'):
            record=manifest['locales'][locale]['files']['supplemental/formal-scoring-rules.json']
            self.assertEqual(json.loads((Path(result['snapshot'])/record['path']).read_text()),rules)

    def test_sealed_target_tampering_rejected(self):
        source=self.candidate();result=publish_content(source,self.store)
        (Path(result['snapshot'])/'en/catalog.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'inventory'): publish_content(source,self.store)

    def test_live2d_bundle_is_published_without_mutating_candidate(self):
        candidate = self.candidate()
        model = candidate / 'global/test-1/public/live2d/test-1/model'
        model.mkdir(parents=True)
        resources = []
        for name, data in [('model.json', b'{}\n'), ('motion.json', b'{"x":1}\n')]:
            (model/name).write_bytes(data)
            resources.append({'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        write(model/'manifest.json', {'model': 'model.json', 'resources': resources, 'totalBytes': sum(r['bytes'] for r in resources)})
        original = (model/'manifest.json').read_bytes()
        meta = json.loads((candidate/'candidate.json').read_text())
        meta['files'] = inventory(candidate, exclude=('candidate.json',))
        write(candidate/'candidate.json', meta)
        result = publish_content(candidate, self.store)
        published = Path(result['snapshot'])/'public/live2d/test-1/model'
        manifest = json.loads((published/'manifest.json').read_text())
        self.assertEqual((model/'manifest.json').read_bytes(), original)
        self.assertTrue((published/manifest['jsonBundle']['file']).is_file())
        self.assertEqual(publish_content(candidate, self.store)['status'], 'unchanged')

    def test_symlink_and_mixed_locale_rejected(self):
        source=self.candidate();(source/'secret').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'symlink'): publish_content(source,self.store)
        (source/'secret').unlink()
        meta=json.loads((source/'candidate.json').read_text());meta['regions'][0]['projections']=[{'locale':'en'}]
        write(source/'candidate.json',meta)
        with self.assertRaisesRegex(ValueError,'locales'): publish_content(source,self.store)

    def test_cross_mount_copy_is_blocked_before_running_out_of_disk(self):
        publish_content(self.candidate(),self.store);previous=(self.store/'current.json').read_bytes()
        next_candidate=self.candidate('cross-mount')
        with patch('tools.content_publication.os.link',side_effect=OSError(errno.EXDEV,'cross mount')), \
             patch('tools.content_publication.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError,'insufficient disk'): publish_content(next_candidate,self.store)
        self.assertEqual((self.store/'current.json').read_bytes(),previous)

if __name__=='__main__': unittest.main()
