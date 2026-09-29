import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.live2d_assets import verify_live2d_assets


class Live2DAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.public = Path(self.temp.name)
        self.folder = self.public / 'live2d/release/model'
        self.folder.mkdir(parents=True)
        files = {'model.model3.json': json.dumps({'FileReferences': {'Moc': 'model.moc3', 'Textures': ['texture.png']}}).encode(),
                 'model.moc3': b'MOC3', 'texture.png': b'texture'}
        self.manifest = {'model': 'model.model3.json', 'totalBytes': sum(map(len, files.values())),
                         'resources': [{'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()]}
        for name, data in files.items(): (self.folder / name).write_bytes(data)
        (self.folder / 'manifest.json').write_text(json.dumps(self.manifest))
        self.catalog = {'releaseId': 'release', 'models': [{'state': 'available', 'root': '/live2d/release/model/', 'bytes': self.manifest['totalBytes']}]}

    def test_complete_resources_are_verified(self):
        self.assertEqual(verify_live2d_assets(self.catalog, self.public, 'release')['resources'], 3)

    def test_other_release_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'another release'):
            verify_live2d_assets(self.catalog, self.public, 'next')

    def test_same_size_corruption_is_rejected(self):
        (self.folder / 'texture.png').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_live2d_assets(self.catalog, self.public, 'release')

    def test_missing_runtime_resource_is_rejected(self):
        (self.folder / 'model.moc3').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            verify_live2d_assets(self.catalog, self.public, 'release')
