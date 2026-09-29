import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from tools.live2d_transport import bundle_model


class Live2DTransportTests(unittest.TestCase):
    def test_bundle_preserves_bytes_and_sealed_hardlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'model'; folder.mkdir()
            files = {'model.json': b'{}\r\n', 'motions/idle.json': '{"label":"灯"}\n'.encode(), 'model.moc3': b'MOC3'}
            resources = []
            for name, data in files.items():
                path = folder / name; path.parent.mkdir(exist_ok=True)
                path.write_bytes(data)
                resources.append({'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            source = root / 'sealed-manifest.json'
            original = json.dumps({'model': 'model.json', 'resources': resources, 'totalBytes': sum(map(len, files.values()))}).encode()
            source.write_bytes(original); os.link(source, folder / 'manifest.json')
            bundle_model(folder)
            self.assertEqual(source.read_bytes(), original)
            manifest = json.loads((folder / 'manifest.json').read_text())
            descriptor = manifest['jsonBundle']; payload = (folder / descriptor['file']).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), descriptor['sha256'])
            self.assertEqual(len(payload), descriptor['bytes'])
            unpacked = json.loads(payload)['files']
            self.assertEqual(set(unpacked), {'model.json', 'motions/idle.json'})
            for name, text in unpacked.items(): self.assertEqual(text.encode(), files[name])
            bundle_model(folder)
            self.assertEqual(json.loads((folder / 'manifest.json').read_text()), manifest)
            (folder / 'model.json').write_bytes(b'bad!')
            with self.assertRaisesRegex(ValueError, 'checksum'): bundle_model(folder)
