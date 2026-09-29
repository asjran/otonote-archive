"""A bound release must never silently accept swapped song audio."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.music_audio_inputs import file_digest, read_music_audio_inputs


class MusicAudioInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        inputs = self.root / 'inputs'
        inputs.mkdir()
        self.audio = inputs / 'song.flac'
        self.audio.write_bytes(b'verified decoded song')
        self.path = inputs / 'report.json'
        self.source = {'region': 'global', 'channel': 'production', 'contentReleaseId': 'release-1'}
        self.report = {
            'schemaVersion': 1, 'identity': dict(self.source), 'complete': True,
            'files': [{'cue_sheet_name': 'M_Song', 'ok': True, 'streams': [{
                'output': 'song.flac', 'size': self.audio.stat().st_size,
                'sha256': file_digest(self.audio),
            }]}],
        }
        self.bind()

    def bind(self):
        self.path.write_text(json.dumps(self.report))
        self.source['musicAudioInputs'] = {'report': 'inputs/report.json', 'sha256': file_digest(self.path)}

    def test_optional_binding_and_valid_portable_payload(self):
        self.assertIsNone(read_music_audio_inputs({}, self.root))
        self.assertEqual(read_music_audio_inputs(self.source, self.root), self.path)

    def test_changed_report_or_audio_is_rejected(self):
        self.path.write_text(self.path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'report digest'):
            read_music_audio_inputs(self.source, self.root)
        self.bind()
        self.audio.write_bytes(b'altered! decoded song')
        with self.assertRaisesRegex(ValueError, 'payload digest/size'):
            read_music_audio_inputs(self.source, self.root)

    def test_other_release_or_partial_import_is_rejected(self):
        self.report['identity']['contentReleaseId'] = 'another-release'
        self.bind()
        with self.assertRaisesRegex(ValueError, 'identity or completeness'):
            read_music_audio_inputs(self.source, self.root)
        self.report['identity']['contentReleaseId'] = 'release-1'
        self.report['complete'] = False
        self.bind()
        with self.assertRaisesRegex(ValueError, 'identity or completeness'):
            read_music_audio_inputs(self.source, self.root)

    def test_duplicate_cue_or_escaped_payload_is_rejected(self):
        self.report['files'].append(copy.deepcopy(self.report['files'][0]))
        self.bind()
        with self.assertRaisesRegex(ValueError, 'duplicate audio record'):
            read_music_audio_inputs(self.source, self.root)
        self.report['files'].pop()
        outside = self.root / 'outside.flac'
        outside.write_bytes(self.audio.read_bytes())
        self.report['files'][0]['streams'][0]['output'] = '../outside.flac'
        self.bind()
        with self.assertRaisesRegex(ValueError, 'escapes input directory'):
            read_music_audio_inputs(self.source, self.root)
