import hashlib
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
