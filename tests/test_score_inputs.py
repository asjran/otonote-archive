import json
import tempfile
import unittest
from pathlib import Path

from tools.score_inputs import read_score_inputs, write_score_inputs
from tools.release_preflight import PreflightError, digest


class ScoreInputsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = {'region': 'global', 'channel': 'production', 'contentReleaseId': 'global-production-a'}
        self.source['scoreInputs'] = write_score_inputs(self.source, {'0001/0001_01.bytes': b'raw score'}, self.root / 'scores')

    def test_bound_bytes_roundtrip_and_unbound_is_explicit(self):
        self.assertEqual(read_score_inputs(self.source), {'0001/0001_01.bytes': b'raw score'})
        self.assertIsNone(read_score_inputs({'region': 'global'}))

    def test_cross_region_or_version_reuse_fails(self):
        for change in [{'region': 'retired'}, {'contentReleaseId': 'global-production-b'}, {'channel': 'staging'}]:
            with self.subTest(change=change), self.assertRaisesRegex(PreflightError, 'identity'):
                read_score_inputs({**self.source, **change})

    def test_changed_index_fails_fixed_digest(self):
        index = Path(self.source['scoreInputs']['index'])
        index.write_text(index.read_text() + ' ')
        with self.assertRaisesRegex(PreflightError, 'index digest'):
            read_score_inputs(self.source)

    def test_changed_payload_fails_even_if_same_size(self):
        next((self.root / 'scores/payloads').iterdir()).write_bytes(b'bad score')
        with self.assertRaisesRegex(PreflightError, 'payload digest'):
            read_score_inputs(self.source)

    def rewrite_index(self, mutate):
        index = Path(self.source['scoreInputs']['index'])
        value = json.loads(index.read_text())
        mutate(value)
        index.write_text(json.dumps(value))
        self.source['scoreInputs']['sha256'] = digest(index)

    def test_empty_and_duplicate_sets_fail(self):
        self.rewrite_index(lambda value: value['scores'].append(value['scores'][0]))
        with self.assertRaisesRegex(PreflightError, 'duplicate'):
            read_score_inputs(self.source)
        self.rewrite_index(lambda value: value.update(scores=[]))
        with self.assertRaisesRegex(PreflightError, 'empty'):
            read_score_inputs(self.source)

    def test_path_traversal_fails(self):
        self.rewrite_index(lambda value: value['scores'][0].update(file='../outside.bytes'))
        with self.assertRaisesRegex(PreflightError, 'unsafe'):
            read_score_inputs(self.source)

    def test_export_refuses_overwrite_or_empty_success(self):
        with self.assertRaisesRegex(PreflightError, 'already exists'):
            write_score_inputs(self.source, {'x.bytes': b'data'}, self.root / 'scores')
        with self.assertRaisesRegex(PreflightError, 'no extracted'):
            write_score_inputs(self.source, {}, self.root / 'empty')
        self.assertFalse((self.root / 'empty').exists())
