import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_preflight import PreflightError, digest
from tools.release_site import build_site, rewrite_data, rewrite_html, prepare_site_workspace


class ReleaseSiteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        renderer = patch('tools.release_site.prepare_site_workspace', return_value=self.root / 'renderer')
        renderer.start()
        self.addCleanup(renderer.stop)
        self.candidate = self.root / 'candidate'
        self.output = self.root / 'web'
        release = 'global-production-test'
        live2d_data = self.root / 'renderer/src/data'
        live2d_data.mkdir(parents=True)
        (live2d_data / 'live2d-catalog.json').write_text(json.dumps({'releaseId': release, 'models': []}))
        path = self.candidate / 'global' / release
        (path / 'public/media').mkdir(parents=True)
        (path / 'public/media/same.webp').write_bytes(b'global')
        for locale in ['zh-CN', 'en']:
            data = path / 'generated/releases' / release / locale
            data.mkdir(parents=True)
            (data / 'catalog.json').write_text(json.dumps({
                'image': '/media/same.webp',
                'projectionContext': {
                    'region': 'global', 'channel': 'production',
                    'contentReleaseId': release, 'locale': locale,
                },
            }))
        files = {str(p.relative_to(self.candidate)): digest(p) for p in self.candidate.rglob('*') if p.is_file()}
        (self.candidate / 'candidate.json').write_text(json.dumps({
            'historicalReplay': False,
            'regions': [{'region': 'global', 'channel': 'production',
                         'contentReleaseId': release, 'path': f'global/{release}',
                         'projections': [{'locale': x} for x in ['zh-CN', 'en']]}],
            'files': files,
        }))

    def fake_run(self, command, **kwargs):
        if command[0] != 'npm':
            return
        env = kwargs['env']
        data = Path(env['OURNOTES_PROJECTION_DATA_ROOT'])
        catalog = json.loads((data / 'catalog.json').read_text())
        index = json.loads((data / 'release-index.json').read_text())
        self.assertEqual(len(index['projections']), 2)
        target = Path(env['OURNOTES_SITE_OUT_DIR'])
        target.mkdir(parents=True)
        (target / 'index.html').write_text(f'<img src="{catalog["image"]}"><a href="/">Home</a>')

    def test_global_assembly_exposes_locales(self):
        with patch('tools.release_site.subprocess.run', side_effect=self.fake_run):
            report = build_site(self.candidate, self.output)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual((self.output / 'media/global/global-production-test/same.webp').read_bytes(), b'global')
        for locale in ['zh-CN', 'en']:
            self.assertIn(f'/global/{locale}/', (self.output / f'global/{locale}/index.html').read_text())
        self.assertIn('/global/zh-CN/', (self.output / 'index.html').read_text())

    def test_renderer_sources_are_copied_and_only_dependencies_are_shared(self):
        project = self.root / 'project'
        (project / 'site/src').mkdir(parents=True)
        (project / 'site/node_modules').mkdir()
        (project / 'config').mkdir()
        (project / 'site/src/page.astro').write_text('original')
        for name in ('astro.config.mjs', 'product-profile.mjs', 'package.json', 'tsconfig.json'):
            (project / 'site' / name).write_text('{}')
        (project / 'config/site-product.json').write_text('{}')
        supplement = project / 'site/public/system-banners'
        supplement.mkdir(parents=True)
        (supplement / 'banner.webp').write_bytes(b'validated image')
        (supplement / 'manifest.json').write_text(json.dumps([{'file': 'banner.webp', 'sha256': digest(supplement / 'banner.webp')}]))
        target = prepare_site_workspace(self.root / 'snapshot/site', root=project)
        (project / 'site/src/page.astro').write_text('changed concurrently')
        self.assertEqual((target / 'src/page.astro').read_text(), 'original')
        self.assertEqual((target / 'node_modules').resolve(), (project / 'site/node_modules').resolve())
        self.assertEqual((target / 'public/system-banners/banner.webp').read_bytes(), b'validated image')

    def test_unlisted_file_is_rejected_before_build(self):
        (self.candidate / 'unexpected.json').write_text('{}')
        with patch('tools.release_site.subprocess.run') as run, self.assertRaisesRegex(PreflightError, 'unlisted'):
            build_site(self.candidate, self.output)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_rehashed_wrong_catalog_identity_is_rejected(self):
        path = next((self.candidate / 'global').glob('*/generated/releases/*/en/catalog.json'))
        value = json.loads(path.read_text())
        value['projectionContext']['region'] = 'unknown'
        path.write_text(json.dumps(value))
        manifest_path = self.candidate / 'candidate.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'][str(path.relative_to(self.candidate))] = digest(path)
        manifest_path.write_text(json.dumps(manifest))
        with patch('tools.release_site.subprocess.run') as run, self.assertRaisesRegex(PreflightError, 'identity'):
            build_site(self.candidate, self.output)
        run.assert_not_called()

    def test_failed_renderer_does_not_publish_partial_site(self):
        with patch('tools.release_site.subprocess.run', side_effect=RuntimeError('render failed')), self.assertRaises(RuntimeError):
            build_site(self.candidate, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.web-*')))

    def test_historical_candidate_is_rejected(self):
        path = self.candidate / 'candidate.json'
        manifest = json.loads(path.read_text())
        manifest['historicalReplay'] = True
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(PreflightError, 'historical'):
            build_site(self.candidate, self.output)

    def test_rewriting_keeps_global_links(self):
        html = '<a href="/global/en/">EN</a><a href="/cards/">Cards</a><img src="/media/global/version/a.png">'
        rewritten = rewrite_html(html, '/global/zh-CN/')
        self.assertIn('href="/global/en/"', rewritten)
        self.assertIn('href="/global/zh-CN/cards/"', rewritten)
        self.assertIn('src="/media/global/version/a.png"', rewritten)
        self.assertEqual(rewrite_data({'/media/a': '/data/x'}, '/global/en/', '/media/global/v/'),
                         {'/media/global/v/a': '/global/en/data/x'})
