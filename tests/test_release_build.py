import functools
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_release_candidates as fixtures
from tools.release_build import build_release
from tools.release_candidates import build_candidates
from tools.release_preflight import PreflightError


class ReleaseBuildTest(unittest.TestCase):
    write_plan = fixtures.ReleaseCandidatesTest.write_plan

    def setUp(self):
        fixtures.ReleaseCandidatesTest.setUp(self)
        self.output = self.root / 'output/release'

    @staticmethod
    def compiler(source, target, locales, root):
        (target / 'public/media').mkdir(parents=True)
        for locale in locales:
            data = target / 'generated/releases' / source['contentReleaseId'] / locale
            data.mkdir(parents=True)
            context = {key: source[key] for key in ('region', 'channel', 'contentReleaseId')}
            (data / 'catalog.json').write_text(json.dumps({'projectionContext': {**context, 'locale': locale}}))
        return {'projections': [{'locale': locale} for locale in locales]}

    @staticmethod
    def renderer(command, **kwargs):
        if command[0] == 'npm':
            target = Path(kwargs['env']['OURNOTES_SITE_OUT_DIR'])
            target.mkdir(parents=True)
            (target / 'index.html').write_text('<a href="/">Home</a>')

    def build(self):
        return build_release(self.plan, self.output, root=self.root)

    def test_real_pipeline_assembles_global_projections_and_report(self):
        with patch('tools.release_build.build_candidates', functools.partial(build_candidates, compiler=self.compiler)), \
             patch('tools.release_site.subprocess.run', side_effect=self.renderer):
            report = self.build()
        self.assertEqual(report['status'], 'built')
        self.assertFalse(report['publicationReady'])
        self.assertEqual(report['validation']['htmlFiles'], 3)
        self.assertTrue((self.output / 'candidate/candidate.json').is_file())
        self.assertTrue((self.output / 'site/global/en/index.html').is_file())
        saved = json.loads((self.output / 'build-report.json').read_text())
        self.assertEqual(saved['sitePath'], 'site')
        self.assertEqual(list(self.output.parent.glob('.release-*')), [])

    def test_render_failure_leaves_existing_build_and_no_partial_output(self):
        old = self.output.parent / 'previous/site/index.html'
        old.parent.mkdir(parents=True)
        old.write_text('previous')
        with patch('tools.release_build.build_candidates', functools.partial(build_candidates, compiler=self.compiler)), \
             patch('tools.release_build.build_site', side_effect=RuntimeError('renderer failed')):
            with self.assertRaisesRegex(RuntimeError, 'renderer failed'):
                self.build()
        self.assertEqual(old.read_text(), 'previous')
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob('.release-*')), [])

    def test_missing_formal_inputs_do_not_generate_or_fall_back(self):
        from tools.release_build import ROOT
        with patch('tools.release_build.build_candidates') as generate:
            with self.assertRaisesRegex(PreflightError, 'not ready'):
                build_release(ROOT / 'config/release-inputs.json', self.output, root=self.root)
        generate.assert_not_called()

    def test_existing_output_is_preserved(self):
        self.output.mkdir(parents=True)
        with self.assertRaisesRegex(PreflightError, 'already exists'):
            self.build()
        self.assertTrue(self.output.is_dir())

    def test_output_cannot_be_source_directory(self):
        self.output = self.root / 'site/new'
        with self.assertRaisesRegex(PreflightError, 'repository output'):
            self.build()
