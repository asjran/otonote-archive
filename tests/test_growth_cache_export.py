import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.growth_cache_export import (
    CACHE_PATH, ExportError, decode_cache, extract_cache_document,
    read_adb_cache, unique_object, write_snapshot,
)


def cache_document():
    return {'_player': {
        '_memberCards': [{'_masterId': 5, '_exp': 120, '_awakeCount': 2,
                          '_rank': 3, '_liveSkillLevel': 4, '_performanceSkillLevel': 2,
                          'credential': 'DO-NOT-EXPORT'}],
        '_supportCards': [{'_masterId': 8, '_exp': 40, '_rank': 2, '_duplicateCount': 1}],
        '_bandItems': [{'_masterId': 9, '_level': 3}],
        '_characters': [{'_masterId': 2, '_exp': 80}],
        '_profileId': 987654321, '_name': 'PRIVATE-NAME',
        '_vip': {'point': 123456},  # unverified cache fields never become trusted data
    }, '_account': 'PRIVATE-ACCOUNT'}


class CacheExportTests(unittest.TestCase):
    def test_real_cache_shape_exports_only_growth(self):
        source = cache_document()
        before = copy.deepcopy(source)
        result = extract_cache_document(source)
        self.assertEqual(source, before)
        self.assertEqual(result['growth']['memberCards'][0]['gekisouSkillLevel'], 2)
        self.assertEqual(result['growth']['supportCards'][0]['duplicateCount'], 1)
        self.assertEqual(result['growth']['bandItems'], [{'masterId': 9, 'level': 3}])
        self.assertEqual(result['growth']['characterRanks'], [{'characterId': 2, 'exp': 80}])
        self.assertIsNone(result['growth']['tgw'])
        self.assertFalse(result['complete'])
        for private in ('PRIVATE', 'DO-NOT-EXPORT', '987654321', '123456', 'credential'):
            self.assertNotIn(private, json.dumps(result))

    def test_missing_scalar_is_unknown_not_zero(self):
        source = cache_document()
        del source['_player']['_memberCards'][0]['_exp']
        result = extract_cache_document(source)
        self.assertIsNone(result['growth']['memberCards'][0]['exp'])
        self.assertIn('exp', result['missingFields']['memberCards'])

    def test_missing_null_and_empty_collection_are_distinguished(self):
        source = cache_document()
        del source['_player']['_memberCards']
        source['_player']['_supportCards'] = None
        source['_player']['_bandItems'] = []
        result = extract_cache_document(source)
        self.assertIsNone(result['growth']['memberCards'])
        self.assertIsNone(result['growth']['supportCards'])
        self.assertEqual(result['growth']['bandItems'], [])
        self.assertEqual(result['coverage']['bandItems'], 'observed')

    def test_invalid_values_and_duplicate_ids_refused(self):
        for value in (True, '20', -1, 2**31, 1.5):
            source = cache_document()
            source['_player']['_memberCards'][0]['_exp'] = value
            with self.subTest(value=value), self.assertRaises(ExportError):
                extract_cache_document(source)
        source = cache_document()
        source['_player']['_memberCards'] *= 2
        with self.assertRaises(ExportError):
            extract_cache_document(source)
        for invalid in ([], {}, {'_player': []}):
            with self.assertRaises(ExportError):
                extract_cache_document(invalid)

    def test_duplicate_json_keys_refused(self):
        with self.assertRaises(ExportError):
            json.loads('{"_player":{},"_player":{}}', object_pairs_hook=unique_object)

    def test_encrypted_cache_round_trip_and_wrong_header(self):
        from analysis.crypto import decrypt_master
        from analysis.crypto.decrypt_master import BLOCK_SIZE
        # Round-trip uses synthetic parameters; production credentials are external.
        DEFAULT_SALT, DEFAULT_IV, DEFAULT_KEY = (bytes([n]) * BLOCK_SIZE for n in (1, 2, 3))
        for name, value in (("DEFAULT_SALT", DEFAULT_SALT), ("DEFAULT_IV", DEFAULT_IV), ("DEFAULT_KEY", DEFAULT_KEY)):
            patcher = patch.object(decrypt_master, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from py3rijndael import Rijndael
        raw = json.dumps(cache_document()).encode()
        padding = BLOCK_SIZE - len(raw) % BLOCK_SIZE
        raw += bytes([padding]) * padding
        cipher = Rijndael(key=DEFAULT_KEY, block_size=BLOCK_SIZE)
        previous = DEFAULT_IV
        encrypted = bytearray(DEFAULT_SALT + DEFAULT_IV)
        for offset in range(0, len(raw), BLOCK_SIZE):
            block = bytes(a ^ b for a, b in zip(raw[offset:offset+BLOCK_SIZE], previous))
            previous = cipher.encrypt(block)
            encrypted.extend(previous)
        self.assertEqual(decode_cache(bytes(encrypted))['growth'],
                         extract_cache_document(cache_document())['growth'])
        for data in (bytes(encrypted[:-1]), b'x' + bytes(encrypted[1:]), b''):
            with self.assertRaises(ExportError):
                decode_cache(data)

    def test_output_private_exclusive_and_symlink_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            snapshot = extract_cache_document(cache_document())
            write_snapshot(path, snapshot)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_snapshot(path, {})
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                write_snapshot(link, {})
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_serial_does_not_spawn_adb(self):
        with patch('subprocess.Popen') as spawn:
            with self.assertRaises(ExportError):
                read_adb_cache('device; something')
            spawn.assert_not_called()
        self.assertTrue(CACHE_PATH.startswith('/sdcard/Android/data/com.bilibili.sirius/files/'))


if __name__ == '__main__':
    unittest.main()
