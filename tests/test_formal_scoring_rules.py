import json
import unittest
import tempfile
from pathlib import Path

from tools.build_formal_scoring_rules import AUDITED_RELEASE_ID, TABLES, build_rules

ROOT = Path(__file__).resolve().parents[1]


class FormalScoringRulesTests(unittest.TestCase):
    def test_unknown_release_cannot_inherit_code_audit(self):
        with self.assertRaisesRegex(ValueError, "not been audited"):
            build_rules(Path("missing"), "future-release")

    def test_checked_in_rules_reproduce_from_current_master(self):
        config = ROOT / "config/release-inputs.json"
        if not config.exists():
            self.skipTest("local production configuration unavailable")
        source = json.loads(config.read_text())["environments"][0]
        master = ROOT / source["masterRoot"]
        if not master.exists():
            self.skipTest("local production Master inputs unavailable")
        self.assertEqual(source["contentReleaseId"], AUDITED_RELEASE_ID)
        expected = build_rules(master, source["contentReleaseId"])
        actual = json.loads((ROOT / "site/src/data/formal-scoring-rules.json").read_text())
        self.assertEqual(actual, expected)
        self.assertTrue({"MasterGekisouSkillEffect", "MasterSkillCumulativeCondition", "MasterEvent", "MasterEventEffect"}.issubset(actual["masterSha256"]))
        self.assertEqual(actual["tables"]["Event"], [])
        self.assertEqual(actual["capabilities"]["gekisouScore"], "state_machine_incomplete")

    def test_rule_projection_includes_upgrade_rows_separately_from_future_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            master = Path(directory)
            for table in TABLES:
                rows = []
                if table == 'BandItem':
                    rows = [{'_id': 101, '_bandId': 1}]
                if table == 'BandItemLevel':
                    rows = [{'_bandItemId': 101, '_level': 1}]
                if table == 'BandItemSkillEffect':
                    rows = [{'_bandItemId': 101, '_level': level} for level in (1, 2)]
                (master / f'Master{table}.json').write_text(json.dumps({'_allData': rows}))
            rules = build_rules(master, AUDITED_RELEASE_ID)
            self.assertEqual(rules['tables']['BandItemLevel'], [{'_bandItemId': 101, '_level': 1}])
            self.assertEqual(len(rules['tables']['BandItemSkillEffect']), 2)
            self.assertIn('MasterBandItemLevel', rules['masterSha256'])


if __name__ == "__main__":
    unittest.main()
