import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.jp_phone_inputs import PhoneResources

class JpCacheTests(unittest.TestCase):
    def test_shared_bytes_require_matching_catalog_binding_and_receipt(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);name='asset_'+'a'*32+'.bundle';payload=b'UnityFS\0test'
            loc=SimpleNamespace(primary_key=name,expected_hash='catalog-hash',expected_size=len(payload),provider_id='provider',resource_type='bundle')
            path=root/name;path.write_bytes(payload)
            sha=hashlib.sha256(payload).hexdigest()
            (root/(name+'.receipt.json')).write_text(json.dumps({'url':'https://cdn.invalid/asset/Android/'+name,'sha256':sha}))
            resource=PhoneResources.__new__(PhoneResources)
            resource.locations={name:loc};resource.shared={};resource.encrypted={};resource.cached={};resource.packaged={};resource.used={}
            prior=SimpleNamespace(locations=[SimpleNamespace(**{**vars(loc),'expected_hash':'another-hash'})],catalog_hash='prior')
            with patch('tools.jp_phone_inputs.CatalogAdapter.parse',return_value=prior):resource.reuse_local(root/'catalog', [root])
            with self.assertRaisesRegex(ValueError,'missing unique'):resource.get(loc)
            prior.locations=[loc]
            with patch('tools.jp_phone_inputs.CatalogAdapter.parse',return_value=prior):resource.reuse_local(root/'catalog',[Path(os.path.relpath(root))])
            self.assertTrue(resource.get(loc).is_absolute())
            self.assertEqual(resource.get(loc).read_bytes(),payload)
            self.assertEqual(resource.used[name]['origin'],'identical-catalog-local-cache')
            path.write_bytes(b'x'*len(payload))
            with self.assertRaisesRegex(ValueError,'digest mismatch'):resource.get(loc)
