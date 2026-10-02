import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from tools.current_resources import CurrentResources
from tools.global_remote_sync import file_hash, write_json


class ResourceCacheTests(unittest.TestCase):
    def test_absent_unchanged_asset_is_downloaded_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource = CurrentResources.__new__(CurrentResources)
            resource.cache = Path(tmp)
            resource.report = {'observation': {'cdnRoot': 'https://example.invalid'}, 'catalogSha256': 'catalog-a'}
            resource.downloaded, resource.budget, resource.imports, resource.used = 0, 100, {}, {}
            name = 'long_' * 45 + '0' * 32 + '.bundle'
            location = SimpleNamespace(primary_key=name, expected_size=4, internal_id='https://dummy.net/asset/Android/' + name)
            def download(url, path, size):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'data')
                receipt = {'url': url, 'byteSize': size, 'sha256': file_hash(path)}
                write_json(path.with_name(path.name + '.receipt.json'), receipt)
                return receipt
            with patch('tools.current_resources.acquire', side_effect=download) as acquire:
                path = resource.get(location)
                self.assertLess(len(path.name), 100)
                self.assertEqual(resource.get(location), path)
                acquire.assert_called_once()
                path.write_bytes(b'evil')
                with self.assertRaisesRegex(ValueError, 'integrity mismatch'): resource.get(location)

    def import_recovery(self, root):
        resource = CurrentResources.__new__(CurrentResources)
        resource.cache = root
        resource.report = {'observation': {'cdnRoot': 'https://example.invalid'}, 'catalogSha256': 'catalog-a'}
        resource.downloaded, resource.budget, resource.used = 0, 100, {}
        name = 'fixture.bundle'
        path = root / 'bundles' / name
        path.parent.mkdir()
        path.write_bytes(b'old!')
        shared = root / 'sealed-reference.bundle'
        os.link(path, shared)
        imported = root / 'import.bundle'
        imported.write_bytes(b'new!')
        resource.imports = {name: (imported, file_hash(imported))}
        location = SimpleNamespace(primary_key=name, expected_size=4,
                                   internal_id='https://dummy.net/asset/Android/' + name)
        return resource, location, path, shared

    def test_local_import_recovery_does_not_overwrite_shared_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource, location, path, shared = self.import_recovery(Path(tmp))
            prior_inode = shared.stat().st_ino
            with patch('tools.current_resources.acquire', side_effect=AssertionError('unexpected network')):
                self.assertEqual(resource.get(location), path)
                self.assertEqual(resource.get(location), path)
            self.assertEqual(path.read_bytes(), b'new!')
            self.assertEqual(shared.read_bytes(), b'old!')
            self.assertEqual(shared.stat().st_ino, prior_inode)
            self.assertNotEqual(path.stat().st_ino, prior_inode)
            self.assertEqual(resource.used[location.primary_key]['sha256'], file_hash(path))
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['fixture.bundle', 'fixture.bundle.receipt.json'])

    def test_failed_or_invalid_import_copy_preserves_old_links_and_cleans_stage(self):
        for failure in ('copy-error', 'wrong-size', 'wrong-digest'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                resource, location, path, shared = self.import_recovery(Path(tmp))
                prior_inode = path.stat().st_ino
                def copy(source, destination):
                    Path(destination).write_bytes(b'corrupt' if failure == 'wrong-size' else b'bad!')
                    if failure == 'copy-error':
                        raise OSError('synthetic copy failure')
                with patch('tools.current_resources.shutil.copyfile', side_effect=copy):
                    with self.assertRaises(OSError if failure == 'copy-error' else ValueError):
                        resource.get(location)
                self.assertEqual(path.read_bytes(), b'old!')
                self.assertEqual(shared.read_bytes(), b'old!')
                self.assertEqual(path.stat().st_ino, prior_inode)
                self.assertEqual(shared.stat().st_ino, prior_inode)
                self.assertEqual(list(path.parent.iterdir()), [path])
                self.assertEqual(resource.used, {})

    def test_raw_cri_key_is_scoped_to_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            resource = CurrentResources.__new__(CurrentResources)
            resource.cache = Path(tmp)
            resource.report = {'observation': {'cdnRoot': 'https://example.invalid'}, 'catalogSha256': 'catalog-a'}
            resource.downloaded, resource.budget, resource.imports, resource.used = 0, 100, {}, {}
            loc = SimpleNamespace(primary_key='cri_assets_cri/sound/bgm', expected_size=4, internal_id='https://dummy.net/asset/Android/cri_assets_cri/sound/bgm')
            paths = []
            def download(url, path, size):
                paths.append(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'data')
                return {'url':url,'sha256':file_hash(path),'byteSize':size}
            with patch('tools.current_resources.acquire',side_effect=download):
                resource.get(loc);resource.report['catalogSha256']='catalog-b';resource.get(loc)
            self.assertNotEqual(paths[0],paths[1])

    def test_typed_texture_resolves_shared_sprite_address(self):
        resource = CurrentResources.__new__(CurrentResources)
        def loc(kind): return SimpleNamespace(resource_type=kind, internal_id='same', dependencies=('bundle',), provider_id=kind)
        resource.by_key = {'icon': [loc('UnityEngine.Sprite'), loc('UnityEngine.Texture2D')]}
        self.assertEqual(resource.locate('icon', 'UnityEngine.Texture2D').resource_type,'UnityEngine.Texture2D')
        with self.assertRaisesRegex(ValueError,'ambiguous'): resource.locate('icon')

class CurrentImageCoverageTests(unittest.TestCase):
    def test_new_asset_ids_and_removals_follow_current_master(self):
        from tools.current_content_inputs import core_image_targets
        class Resources:
            catalog = SimpleNamespace(locations=[])
            members = [{'_id': 999, '_assetID': 2001}]
            def rows(self,name): return self.members if name=='MasterMemberCard' else []
            def prefix(self,name): return name
        resource=Resources()
        first=core_image_targets(resource)
        self.assertEqual(list(first),['Assets/AddressableResources/MemberCard/2001/member_full.png'])
        resource.members=[{'_id':1000,'_assetID':2002}]
        second=core_image_targets(resource)
        self.assertEqual(list(second),['Assets/AddressableResources/MemberCard/2002/member_full.png'])
