import json
from pathlib import Path
import tempfile
import unittest

from tools.bgm_catalog import classify, selected_streams, read_bgm_inputs, project_bgm
from tools.music_audio_inputs import file_digest


class BgmCatalogTests(unittest.TestCase):
    def test_shared_cue_copies_are_removed_but_subsongs_are_preserved(self):
        records = [
            {'cue_sheet_name': 'Bgm', 'streams': [{'name': 'sound_bgm_gacha', 'subsong': 2}, {'name': 'sound_bgm_gacha', 'subsong': 3}]},
            {'cue_sheet_name': 'sound_bgm_gacha', 'streams': [{'name': 'sound_bgm_gacha', 'subsong': 1}, {'name': 'sound_bgm_gacha', 'subsong': 2}]},
        ]
        cue, selected = list(selected_streams(records))[0]
        self.assertEqual(cue, 'sound_bgm_gacha')
        self.assertEqual([stream['subsong'] for _, stream in selected], [1, 2])
        self.assertTrue(all(record['cue_sheet_name'] == cue for record, _ in selected))

    def test_only_evidenced_scene_labels_are_assigned(self):
        self.assertEqual(classify('sound_bgm_home', '', 'zh-CN'), ('home', '主界面', True))
        self.assertEqual(classify('sound_bgm_birthday', '', 'en')[0], 'event')
        self.assertEqual(classify('sound_bgm_adv_home_swing', '', 'zh-CN')[0], 'story')
        self.assertEqual(classify('event_unknown', '', 'zh-CN'), ('other', 'event_unknown', False))

    def test_unbound_audio_is_pending_and_master_duplicates_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'master').mkdir()
            (root / 'master/MasterSound.json').write_text(json.dumps({'_allData': [
                {'_cueName': 'sound_bgm_home'}, {'_cueName': 'sound_bgm_home'}, {'_cueName': 'voice_001'}]}))
            catalog = project_bgm({'masterRoot': 'master', 'contentReleaseId': 'r1'}, root, root / 'public', 'zh-CN')
            self.assertEqual(len(catalog['tracks']), 1)
            self.assertEqual(catalog['tracks'][0]['status'], 'missing')
            self.assertIsNone(catalog['tracks'][0]['audio'])

    def test_report_rejects_wrong_release_tampering_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'audio'
            folder.mkdir()
            payload = folder / 'track.flac'
            payload.write_bytes(b'test audio')
            report_path = folder / 'report.json'
            source = {'region': 'global', 'channel': 'production', 'contentReleaseId': 'r1'}
            report = {'schemaVersion': 1, 'complete': True, 'identity': dict(source), 'files': [
                {'cue_sheet_name': 'sound_bgm_home', 'ok': True, 'streams': [
                    {'output': 'track.flac', 'sha256': file_digest(payload), 'size': payload.stat().st_size,
                     'validation': {'ok': True}, 'duration_seconds': 10}]}]}

            def bind():
                report_path.write_text(json.dumps(report))
                source['bgmAudioInputs'] = {'report': 'audio/report.json', 'sha256': file_digest(report_path)}

            bind()
            self.assertIsNotNone(read_bgm_inputs(source, root))
            payload.write_bytes(b'bad! audio')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                read_bgm_inputs(source, root)
            payload.write_bytes(b'test audio')
            report['identity']['contentReleaseId'] = 'wrong'
            bind()
            with self.assertRaisesRegex(ValueError, 'release'):
                read_bgm_inputs(source, root)
            report['identity']['contentReleaseId'] = 'r1'
            report['files'][0]['streams'][0]['output'] = '../outside.flac'
            bind()
            with self.assertRaisesRegex(ValueError, 'integrity'):
                read_bgm_inputs(source, root)


if __name__ == '__main__':
    unittest.main()
