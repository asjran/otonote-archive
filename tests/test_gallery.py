"""Exercise real gallery input integrity and release/locale bindings."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.gallery import project_gallery

ROOT = Path(__file__).resolve().parents[1]

class GalleryTests(unittest.TestCase):
    def setUp(self):
        source = json.loads((ROOT / 'config/release-inputs.json').read_text())['environments'][0]
        self.master = ROOT / source['masterRoot']
        self.release = source['contentReleaseId']

    def test_complete_unique_master_binding_and_localization(self):
        zh = project_gallery(self.master, self.release, 'zh-CN')
        en = project_gallery(self.master, self.release, 'en')
        self.assertEqual((len(zh['comics']), len(zh['stamps']), len(zh['stickers']), len(zh['backgrounds'])), (25, 81, 257, 28))
        self.assertEqual(zh['sourceReleaseId'], self.release)
        self.assertEqual(en['locale'], 'en')
        self.assertNotEqual(zh['stickers'][0]['title'], en['stickers'][0]['title'])
        for kind, table in [('comics', 'MasterLoadingComics'), ('stamps', 'MasterStamp'), ('stickers', 'MasterDegree'), ('backgrounds', 'MasterBackground')]:
            ids = {r['_id'] for r in json.loads((self.master / f'{table}.json').read_text())['_allData']}
            self.assertEqual({r['id'] for r in zh[kind]}, ids)
            self.assertEqual(len(ids), len(zh[kind]))
            self.assertTrue(all(r['width'] > 0 and r['height'] > 0 for r in zh[kind] if r['status'] == 'available'))

    def test_missing_image_stays_explicit_without_download(self):
        value = project_gallery(self.master, self.release, 'zh-CN')
        missing = [r for r in value['stickers'] if r['status'] == 'missing']
        self.assertEqual([r['id'] for r in missing], [10000107])
        self.assertIsNone(missing[0]['image'])
        self.assertIsNone(missing[0]['thumbnail'])

    def test_stamps_and_profile_stickers_have_separate_identity(self):
        value = project_gallery(self.master, self.release, 'zh-CN')
        stamp = next(r for r in value['stamps'] if r['id'] == 1)
        sticker = next(r for r in value['stickers'] if r['id'] == 1)
        self.assertNotEqual(stamp['image'], sticker['image'])
        self.assertEqual(stamp['mediaType'], 'stamps')
        self.assertEqual(sticker['category'], 'stickers')
        self.assertEqual(len([r for r in value['backgrounds'] if r['status'] == 'available']), 28)

    def test_rejects_changed_master(self):
        from tools.gallery import digest
        with patch('tools.gallery.digest', side_effect=lambda p: 'changed' if p.name == 'MasterStamp.json' else digest(p)):
            with self.assertRaisesRegex(ValueError, 'reverified'):
                project_gallery(self.master, self.release, 'zh-CN')

    def test_rejects_corrupt_image(self):
        from tools.gallery import digest
        with patch('tools.gallery.digest', side_effect=lambda p: 'corrupt' if p.suffix == '.png' else digest(p)):
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                project_gallery(self.master, self.release, 'zh-CN')

    def test_reduced_fixture_has_no_invented_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            value = project_gallery(Path(folder), 'fixture', 'en')
            self.assertEqual(value['comics'] + value['stickers'], [])

if __name__ == '__main__':
    unittest.main()
