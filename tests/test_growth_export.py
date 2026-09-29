from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from tools.growth_export import ExportError, MAX_BYTES, extract_growth, main


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def integer(number, value):
    return varint(number << 3) + varint(value)


def message(number, data):
    return varint((number << 3) | 2) + varint(len(data)) + data


# These field numbers are independent fixtures from the native client field
# constants/descriptors, not imported from the implementation's allowlist.
def account_response():
    member = bytes.fromhex('106518d2092002280330043805400150075802')
    support = bytes.fromhex('10ca0118c80328023804')
    instrument = bytes.fromhex('0865100a')
    character = bytes.fromhex('08031015')
    tgw = bytes.fromhex('08a01f380f')  # point 4000; claimed reward rank 15 must not be exported
    player = (message(2, integer(1, 7654321) + member + message(200, b'PRIVATE-TOKEN'))
              + message(3, support) + message(8, instrument)
              + message(12, character) + message(50, tgw)
              + message(34, b'PRIVATE-NAME') + message(6, b'PRIVATE-WALLET'))
    return message(1, player) + integer(6, 987654321) + message(8, b'PRIVATE-ACCOUNT')


class GrowthExportTests(unittest.TestCase):
    def test_extracts_five_groups_and_drops_sensitive_fields(self):
        result = extract_growth(account_response())
        self.assertEqual(result['growth']['memberCards'][0], {
            'masterId': 101, 'exp': 1234, 'awakeCount': 2, 'cardRank': 3,
            'leaderSkillLevel': 4, 'liveSkillLevel': 5, 'performanceSkillLevel': 1,
            'linkSkillLevel': 7, 'gekisouSkillLevel': 2,
        })
        self.assertEqual(result['growth']['supportCards'], [
            {'masterId': 202, 'exp': 456, 'cardRank': 2, 'duplicateCount': 4}])
        self.assertEqual(result['growth']['bandItems'], [{'masterId': 101, 'level': 10}])
        self.assertEqual(result['growth']['characterRanks'], [{'characterId': 3, 'exp': 21}])
        self.assertEqual(result['growth']['tgw'], {'point': 4000})
        self.assertFalse(result['complete'])
        serialized = json.dumps(result)
        for secret in ['PRIVATE', '987654321', '7654321', 'gainedRewardRank']:
            self.assertNotIn(secret, serialized)

    def test_unobserved_groups_are_unknown_not_empty(self):
        result = extract_growth(message(1, b''))
        self.assertTrue(all(v is None for v in result['growth'].values()))
        self.assertTrue(all(v == 'not_observed' for v in result['coverage'].values()))

    def test_observed_zero_point_message_has_proto3_default(self):
        result = extract_growth(message(1, message(50, b'')))
        self.assertEqual(result['growth']['tgw'], {'point': 0})
        self.assertEqual(result['coverage']['tgw'], 'observed')

    def test_grpc_frame_and_compression_rejection(self):
        data = account_response()
        frame = b'\0' + len(data).to_bytes(4, 'big') + data
        self.assertEqual(extract_growth(frame, grpc_frame=True)['growth'], extract_growth(data)['growth'])
        for invalid in [b'\1' + frame[1:], frame[:-1], frame + b'\0', b'']:
            with self.subTest(invalid_length=len(invalid)), self.assertRaises(ExportError):
                extract_growth(invalid, grpc_frame=True)

    def test_missing_or_duplicate_player_data_is_rejected(self):
        for data in [b'', integer(1, 1), message(1, b'') * 2]:
            with self.subTest(data=data), self.assertRaises(ExportError):
                extract_growth(data)

    def test_truncated_and_overflow_wire_data_is_rejected(self):
        for data in [b'\x80', b'\x0a\x05\0', b'\0', b'\x0b', b'\x08' + b'\xff' * 10]:
            with self.subTest(data=data), self.assertRaises(ExportError):
                extract_growth(data)

    def test_known_field_with_wrong_type_or_duplicate_is_rejected(self):
        for record in [message(2, b'1'), integer(2, 1) * 2, b'']:
            with self.subTest(record=record), self.assertRaises(ExportError):
                extract_growth(message(1, message(2, record)))

    def test_repeated_ids_and_duplicate_tgw_are_rejected(self):
        for player in [message(8, integer(1, 1)) * 2, message(50, b'') * 2]:
            with self.subTest(player=player), self.assertRaises(ExportError):
                extract_growth(message(1, player))

    def test_negative_and_unsafe_integers_are_rejected(self):
        for record in [integer(2, 1 << 53), integer(2, 1) + integer(3, (1 << 64) - 1)]:
            with self.subTest(record=record), self.assertRaises(ExportError):
                extract_growth(message(1, message(2, record)))

    def test_oversized_input_is_rejected(self):
        with self.assertRaisesRegex(ExportError, 'response_too_large'):
            extract_growth(b'\0' * (MAX_BYTES + 1))

    def test_cli_private_file_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            source = Path(directory) / 'response.bin'
            output = Path(directory) / 'growth.json'
            source.write_bytes(account_response())
            self.assertEqual(main([str(source), '--output', str(output)]), 0)
            original = output.read_bytes()
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(main([str(source), '--output', str(output)]), 2)
            self.assertEqual(output.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_cli_rejects_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            source = Path(directory) / 'source'
            target = Path(directory) / 'target'
            output = Path(directory) / 'link'
            source.write_bytes(account_response())
            target.write_text('keep')
            output.symlink_to(target)
            self.assertEqual(main([str(source), '--output', str(output)]), 2)
            self.assertEqual(target.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
