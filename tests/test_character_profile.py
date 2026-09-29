"""Profile text must come from the selected package and respect locale fallbacks."""
import unittest

from tools.master_catalog import MasterData, build_master_entities


class CharacterProfileTest(unittest.TestCase):
    def character(self, locale="zh-CN", **fields):
        row = {"_id": 1, "_bandID": 1, **fields}
        master = MasterData(
            characters={1: row}, bands={1: {"_id": 1}}, member_cards={},
            support_cards={}, texts={
                "bio": {"_simplifiedChinese": " 第一行\r\n第二行 ", "_english": " Biography "},
                "hobby": {"_japanese": "なし", "_simplifiedChinese": "无"},
                "voice": {"_japanese": "CV. 羊宮 妃那"},
            }
        )
        entities, _ = build_master_entities(master, [], {}, "release-test", locale)
        return entities["characters"][0]["profile"]

    def test_localized_description_preserves_paragraphs(self):
        fields = {"_descriptionTextId": "bio"}
        self.assertEqual(self.character(**fields)["description"], "第一行\n第二行")
        self.assertEqual(self.character("en", **fields)["description"], "Biography")

    def test_missing_and_dangling_text_never_becomes_profile_content(self):
        profile = self.character(_bloodTypeTextId="", _schoolTextId="unknown")
        self.assertEqual(profile["bloodType"], "")
        self.assertEqual(profile["school"], "")
        self.assertTrue(all(value == "" for value in profile.values()))

    def test_explicit_none_is_valid_content(self):
        self.assertEqual(self.character(_hobbyTextId="hobby")["hobby"], "无")

    def test_profile_uses_existing_localization_fallback(self):
        self.assertEqual(self.character("en", _voiceActorTextId="voice")["voiceActor"], "CV. 羊宮 妃那")


if __name__ == "__main__":
    unittest.main()
