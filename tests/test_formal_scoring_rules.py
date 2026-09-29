import json
import unittest
from pathlib import Path

from tools.build_formal_scoring_rules import AUDITED_RELEASE_ID, build_rules

ROOT = Path(__file__).resolve().parents[1]


class FormalScoringRulesTests(unittest.TestCase):
    def test_unknown_release_cannot_inherit_code_audit(self):
        with self.assertRaisesRegex(ValueError, "not been audited"):
            build_rules(Path("missing"), "future-release")

    def test_checked_in_rules_reproduce_from_current_master(self):
        source = json.loads((ROOT / "config/release-inputs.json").read_text())["environments"][0]
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


if __name__ == "__main__":
    unittest.main()
