import hashlib
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil
import time
from unittest.mock import patch
from tools.publish_prerender import publish, read_inputs


class PrerenderPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.code = self.root/'code'; self.content = self.root/'content'; self.output = self.root/'rendered'
        files = {'prerender/render.mjs':hashlib.sha256(b'fixture').hexdigest()}
        self.identity = hashlib.sha256(json.dumps(files,separators=(',',':')).encode()).hexdigest()[:24]
        release = self.code/'releases'/self.identity
        (release/'compiled/prerender').mkdir(parents=True)
        (release/'compiled/prerender/render.mjs').write_bytes(b'fixture')
        (release/'code-release.json').write_text(json.dumps({'codeId':self.identity,'files':files}))
        (self.code/'current').symlink_to('releases/'+self.identity)
        self.pointer('a'*24)
        self.calls = []

    def tearDown(self): self.tmp.cleanup()

    def pointer(self, identity, region="global"):
        path = self.content/'releases'/identity
        path.mkdir(parents=True)
        manifest = json.dumps({'region':region}).encode()
        (path/'manifest.json').write_bytes(manifest)
        pointer = {'schemaVersion':1,'manifest':'/content/releases/'+identity+'/manifest.json','sha256':hashlib.sha256(manifest).hexdigest()}
        pointer_path = self.content/('current.json' if region=='global' else 'jp/current.json')
        pointer_path.parent.mkdir(parents=True,exist_ok=True)
        pointer_path.write_text(json.dumps(pointer))

    def render(self, args, **kwargs):
        stage = Path(args[5]); locale = args[6]; region = args[8] if len(args)>8 else 'global'
        self.calls.append(locale)
        pointer = json.loads(Path(args[7]).read_text())
        (stage/('report-'+region+'-'+locale+'.json')).write_text(json.dumps({'codeId':self.identity,'pointer':pointer,'region':region,'locale':locale}))
        for route in ('','characters','cards/members','cards/supports','music','database/items','database/skills','tools/live2d'):
            target = stage/region/locale/route/'index.html'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('<html data-prerendered="true"><main>ok</main></html>')

    def test_success_and_unchanged_skip(self):
        result = publish(self.code,self.content,self.output,self.render)
        self.assertEqual(result['status'],'published')
        self.assertEqual(self.calls,['zh-CN','en'])
        self.assertEqual(publish(self.code,self.content,self.output,self.render)['status'],'unchanged')
        self.assertEqual(len(self.calls),2)

    def test_corrupt_optional_edition_keeps_native_pages_usable(self):
        self.pointer('b'*24, 'jp')
        (self.content/'releases'/('b'*24)/'manifest.json').write_text('{}')
        pointer = json.loads(read_inputs(self.code,self.content)[2])
        self.assertEqual(pointer['libraryPointers'], {'jp': None})
        self.assertEqual(publish(self.code,self.content,self.output,self.render)['status'], 'published')

    def test_refresh_keeps_consistent_view_then_falls_back_after_persistent_failure(self):
        publish(self.code,self.content,self.output,self.render)
        original = (self.output/'current').resolve()
        self.pointer('b'*24)
        def fail(*args,**kwargs): raise subprocess.CalledProcessError(1,'node')
        with self.assertRaises(subprocess.CalledProcessError): publish(self.code,self.content,self.output,fail)
        self.assertEqual((self.output/'current').resolve(),original)
        self.assertEqual((self.output/'previous').resolve(),original)
        self.assertFalse(list((self.output/'releases').glob('.render-*')))
        with patch('tools.publish_prerender.time.time',return_value=time.time()+601):
            with self.assertRaises(subprocess.CalledProcessError): publish(self.code,self.content,self.output,fail)
        self.assertFalse((self.output/'current').is_symlink())

    def test_refresh_serves_previous_until_both_locales_finish(self):
        publish(self.code,self.content,self.output,self.render)
        original=(self.output/'current').resolve()
        self.pointer('e'*24)
        def render(args,**kwargs):
            self.assertEqual((self.output/'current').resolve(),original)
            self.render(args,**kwargs)
        publish(self.code,self.content,self.output,render)
        self.assertNotEqual((self.output/'current').resolve(),original)

    def test_concurrent_pointer_change_never_activates_old_candidate(self):
        def change(args,**kwargs):
            self.render(args,**kwargs)
            if args[6]=='en': self.pointer('c'*24)
        self.assertEqual(publish(self.code,self.content,self.output,change)['status'],'superseded')
        self.assertFalse((self.output/'current').is_symlink())

    def test_corrupt_renderer_does_not_publish(self):
        ((self.code/'current').resolve()/'compiled/prerender/render.mjs').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'Invalid compiled file'): publish(self.code,self.content,self.output,self.render)
        self.assertFalse(self.calls)

    def test_retired_html_can_be_regenerated_without_losing_open_tab_payloads(self):
        publish(self.code,self.content,self.output,self.render)
        final = (self.output/'current').resolve()
        (final/'payloads').mkdir()
        (final/'payloads/old.json').write_text('{}')
        (self.output/'current').unlink()
        shutil.rmtree(final/'global')
        self.assertEqual(publish(self.code,self.content,self.output,self.render)['status'],'published')
        self.assertTrue((final/'global/en/music/index.html').is_file())
        self.assertEqual((final/'payloads/old.json').read_text(),'{}')

    def test_publication_preserves_all_historical_html_and_payloads_even_after_a_week(self):
        publish(self.code,self.content,self.output,self.render)
        first = (self.output/'current').resolve()
        (first/'payloads').mkdir()
        (first/'payloads/open-tab.json').write_text('{}')
        expired=time.time()-8*86400
        os.utime(first,(expired,expired))
        before={path:(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns)
                for path in first.rglob('*') if path.is_file()}
        for digit in 'bcde':
            self.pointer(digit*24)
            result=publish(self.code,self.content,self.output,self.render)
        self.assertTrue((first/'global/en/music/index.html').is_file())
        self.assertEqual(before,{path:(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns) for path in before})
        self.assertEqual(len(list((self.output/'releases').iterdir())),5)
        self.assertEqual(result['retention'],{'status':'deferred_to_operations'})
        self.assertTrue(((self.output/'current').resolve()/'global').is_dir())

    def test_partial_failed_stage_is_removed_without_changing_previous_release(self):
        publish(self.code,self.content,self.output,self.render)
        previous=(self.output/'current').resolve()
        before={path:path.read_bytes() for path in previous.rglob('*') if path.is_file()}
        self.pointer('b'*24)
        def fail_second(args,**kwargs):
            self.render(args,**kwargs)
            if args[6]=='en':raise subprocess.CalledProcessError(1,'node')
        with self.assertRaises(subprocess.CalledProcessError):
            publish(self.code,self.content,self.output,fail_second)
        self.assertEqual((self.output/'current').resolve(),previous)
        self.assertEqual((self.output/'previous').resolve(),previous)
        self.assertEqual(before,{path:path.read_bytes() for path in before})
        self.assertFalse(list((self.output/'releases').glob('.render-*')))

    def test_jp_uses_own_pointer_and_switch_without_touching_global(self):
        publish(self.code,self.content,self.output,self.render)
        original=(self.output/'current').resolve()
        self.pointer('f'*24,'jp')
        result=publish(self.code,self.content,self.output,self.render,region='jp')
        self.assertEqual(result['status'],'published')
        jp=(self.output/'current-jp').resolve()
        self.assertEqual(jp.name,read_inputs(self.code,self.content,'jp')[3])
        saved=json.loads((jp/'pointer.json').read_text())
        self.assertEqual(saved['libraryPointers']['global']['manifest'],'/content/releases/'+'a'*24+'/manifest.json')
        self.assertTrue((jp/'jp/en/music/index.html').is_file())
        self.assertFalse((jp/'global').exists())
        self.assertEqual((self.output/'current').resolve(),original)
        # Adding JP changes the shared Global directory even if Global itself stayed put.
        self.assertEqual(publish(self.code,self.content,self.output,self.render)['status'],'published')
        self.assertEqual(publish(self.code,self.content,self.output,self.render,region='jp')['status'],'unchanged')

    def test_other_edition_refresh_invalidates_shared_render(self):
        self.pointer('f'*24,'jp')
        publish(self.code,self.content,self.output,self.render)
        old=(self.output/'current').resolve()
        self.pointer('e'*24,'jp')
        self.assertEqual(publish(self.code,self.content,self.output,self.render)['status'],'published')
        self.assertNotEqual((self.output/'current').resolve(),old)

    def test_jp_rejects_global_content_pointer(self):
        (self.content/'jp').mkdir()
        shutil.copy(self.content/'current.json',self.content/'jp/current.json')
        with self.assertRaisesRegex(ValueError,'region'):
            publish(self.code,self.content,self.output,self.render,region='jp')
        self.assertFalse(self.calls)

    def test_jp_failure_and_history_leave_global_view_untouched(self):
        publish(self.code,self.content,self.output,self.render)
        original=(self.output/'current').resolve()
        for digit in 'bcde':
            self.pointer(digit*24,'jp')
            publish(self.code,self.content,self.output,self.render,region='jp')
        self.assertTrue((original/'global/en/music/index.html').is_file())
        self.assertEqual((self.output/'current').resolve(),original)
        previous=(self.output/'current-jp').resolve()
        self.pointer('f'*24,'jp')
        def fail(*args,**kwargs): raise subprocess.CalledProcessError(1,'node')
        with self.assertRaises(subprocess.CalledProcessError):
            publish(self.code,self.content,self.output,fail,region='jp')
        self.assertEqual((self.output/'current-jp').resolve(),previous)
        with patch('tools.publish_prerender.time.time',return_value=time.time()+601):
            with self.assertRaises(subprocess.CalledProcessError):
                publish(self.code,self.content,self.output,fail,region='jp')
        self.assertFalse((self.output/'current-jp').is_symlink())
        self.assertEqual((self.output/'current').resolve(),original)

    def test_retired_jp_html_can_be_regenerated(self):
        self.pointer('b'*24,'jp')
        publish(self.code,self.content,self.output,self.render,region='jp')
        final=(self.output/'current-jp').resolve()
        (self.output/'current-jp').unlink()
        shutil.rmtree(final/'jp')
        self.assertEqual(publish(self.code,self.content,self.output,self.render,region='jp')['status'],'published')
        self.assertTrue((final/'jp/en/music/index.html').is_file())


    def test_jp_candidate_superseded_by_its_own_update(self):
        self.pointer('b'*24,'jp')
        def change(args,**kwargs):
            self.render(args,**kwargs)
            if args[6]=='en': self.pointer('c'*24,'jp')
        self.assertEqual(publish(self.code,self.content,self.output,change,region='jp')['status'],'superseded')
        self.assertFalse((self.output/'current-jp').is_symlink())


if __name__ == '__main__': unittest.main()
