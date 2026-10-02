from pathlib import Path
import tempfile
import unittest
from tools.global_remote_sync import write_json
from tools.update_retention import cleanup,history


class RetentionTests(unittest.TestCase):
    def test_current_previous_and_unmanaged_files_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'web';workspace=Path(tmp)/'work';releases=root/'releases';releases.mkdir(parents=True)
            for name in ('auto-'+ 'a'*20,'auto-'+ 'b'*20,'auto-'+ 'c'*20,'manual'):
                folder=releases/name;folder.mkdir()
                if name.startswith('auto-'):write_json(folder/'.update-release.json',{'identity':name[5:]+'d'*44})
            (root/'current').symlink_to(releases/('auto-'+'a'*20));(root/'previous').symlink_to(releases/('auto-'+'b'*20))
            keep=workspace/'builds'/('a'*20);old=workspace/'builds'/('b'*20)
            for folder in (keep,old):write_json(folder/'package/bundle.json',{})
            sync=workspace/'sync-complete';current=sync/'1.0.0.1-aaaaaaaa-bbbbbbbb-complete-v2-cccccccc';expired=sync/'1.0.0.2-aaaaaaaa-bbbbbbbb-complete-v2-cccccccc'
            for folder in (current,expired):write_json(folder/'inputs/release-inputs.json',{})
            write_json(sync/'state.json',{'inputPlan':str(current/'inputs/release-inputs.json'),'snapshot':str(current/'snapshot')})
            result=cleanup(workspace,root,[str(keep)])
            self.assertTrue(keep.exists());self.assertFalse(old.exists());self.assertTrue(current.exists());self.assertFalse(expired.exists())
            self.assertTrue((releases/'manual').exists());self.assertTrue((root/'previous').resolve().exists());self.assertFalse((releases/('auto-'+'c'*20)).exists())
    def test_history_deduplicates_repeated_unchanged_runs(self):
        self.assertEqual(history({'buildDirectory':'a','retainedBuilds':['a','b']},{'buildDirectory':'a'}),['a','b'])
