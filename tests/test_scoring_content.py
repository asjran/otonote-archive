import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.scoring_content import bind_scoring_rules, TABLES


class ScoringContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        song = {'_id':1, '_musicType':1, '_bestMusicTagIDs':[2],
                '_gekisouMission1':1, '_gekisouMission2':1, '_gekisouMission3':1}
        self.base = {'sourceReleaseId':'baseline','verificationStatus':'code_audited',
                     'masterSha256':{},'tables':{'LiveMusic':[song], 'LiveMusicScore':[{'_id':100},{'_id':200}]},
                     'nativeSha256':'native','native':{'sourceReleaseId':'baseline','nativeSha256':'native'},
                     'capabilities':{'formationPower':'code_audited'}}
        for name in TABLES:
            raw = json.dumps({'_allData':self.base['tables'].get(name,[])}).encode()
            (self.root/f'Master{name}.json').write_bytes(raw)
            self.base['masterSha256'][f'Master{name}'] = hashlib.sha256(raw).hexdigest()

    def test_current_content_uses_reference_without_relabelling_native_audit(self):
        path = self.root/'MasterLiveMusic.json'; song = self.base['tables']['LiveMusic'][0]
        path.write_text(json.dumps({'_allData':[song,{**song,'_id':2}]}))
        rules = bind_scoring_rules(self.root,'current',self.base)
        self.assertEqual(rules['sourceReleaseId'],'current')
        self.assertEqual(rules['verificationStatus'],'reference_compatible')
        self.assertEqual(rules['native']['sourceReleaseId'],'baseline')
        self.assertFalse(rules['referenceProfile']['currentGameplayVerified'])
        self.assertEqual(len(rules['tables']['LiveMusic']),2)
        self.assertEqual(self.base['verificationStatus'],'code_audited')

    def test_formula_or_old_song_changes_are_rejected(self):
        path=self.root/'MasterParameter.json'; old=path.read_bytes()
        path.write_text('{"_allData":[{"_id":1,"_value":999}]}')
        self.assertEqual(bind_scoring_rules(self.root,'current',self.base)['verificationStatus'],'unavailable')
        path.write_bytes(old)
        song={**self.base['tables']['LiveMusic'][0],'_musicType':999}
        (self.root/'MasterLiveMusic.json').write_text(json.dumps({'_allData':[song]}))
        self.assertEqual(bind_scoring_rules(self.root,'current',self.base)['reason'],'changed_song_rules')

    def test_unknown_song_and_missing_input_cannot_enable_tools(self):
        song=self.base['tables']['LiveMusic'][0]
        (self.root/'MasterLiveMusic.json').write_text(json.dumps({'_allData':[song,{**song,'_id':3}]}))
        self.assertEqual(bind_scoring_rules(self.root,'current',self.base)['reason'],'unsupported_song_rules')
        (self.root/'MasterMemberCard.json').unlink()
        self.assertEqual(bind_scoring_rules(self.root,'current',self.base)['verificationStatus'],'unavailable')

    def test_audited_release_requires_identical_hashes(self):
        self.assertEqual(bind_scoring_rules(self.root,'baseline',self.base),self.base)
        path=self.root/'MasterLiveMusic.json';path.write_text(path.read_text()+' ')
        self.assertEqual(bind_scoring_rules(self.root,'baseline',self.base)['verificationStatus'],'unavailable')
