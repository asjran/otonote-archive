from __future__ import annotations

import unittest
from pathlib import Path

from tools.card_taxonomy import build_band_logo_index, build_card_taxonomy


class CardTaxonomyTest(unittest.TestCase):
    def test_global_embedded_sprite_names_resolve_without_rewriting_provenance(self) -> None:
        from tools.build_site_catalog import texture_records
        import tempfile
        names = [*(f"sp_icon_live_music_type_{code}" for code in (1, 3, 4, 5, 99)),
                 "sp_icon_member_card_type_2",
                 *(f"RarityIconCenter_{label}" for label in ("R", "SR", "SSR", "BD", "EX")),
                 "MemberExpIcon", "SnapExpIcon", "SpecialTraining", "Icon_Awakened", "awakening_base"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                (root / f"{name}.png").touch()
            manifest = {"assets": [{"type": "Sprite", "name": name, "exported_file": f"{name}.png"}
                                   for name in [*names, "unrelated_sprite"]]}
            (root / "unrelated_sprite.png").touch()
            records = texture_records(manifest, root)
            self.assertEqual({r["name"] for r in records}, set(names))
            taxonomy = build_card_taxonomy(records, {str(r["source_file"]): r["name"] for r in records})
        self.assertEqual(taxonomy["attributes"][1]["iconAssetId"], "sp_icon_member_card_type_2")
        self.assertEqual(taxonomy["rarities"][2]["label"], "SSR")
        self.assertEqual(taxonomy["rarities"][2]["iconAssetId"], "RarityIconCenter_SSR")
        # Global 1.0.1 App.Master.CardRarity: EX=10, BD=20.
        # Support cards 61 and 70 use 10; it must resolve to the EX sprite.
        rarities = {rarity["code"]: rarity for rarity in taxonomy["rarities"]}
        self.assertEqual((rarities[10]["label"], rarities[10]["iconAssetId"]),
                         ("EX", "RarityIconCenter_EX"))
        self.assertEqual((rarities[20]["label"], rarities[20]["iconAssetId"]),
                         ("BD", "RarityIconCenter_BD"))
        self.assertEqual(taxonomy["growthIcons"]["rank"], "SpecialTraining")

    def test_builds_normal_and_inverse_band_logo_index(self) -> None:
        records = [
            {
                "source_file": Path("/tmp/band-2-logo.png"),
                "name": "band_logo",
                "container_path": (
                    "Assets/AddressableResources/Band/2/band_logo.png"
                ),
            },
            {
                "source_file": Path("/tmp/band-2-logo-white.png"),
                "name": "band_logo_white",
                "container_path": (
                    "Assets/AddressableResources/Band/2/"
                    "band_logo_white.png"
                ),
            },
        ]
        asset_ids = {
            "/tmp/band-2-logo.png": "asset-band-2",
            "/tmp/band-2-logo-white.png": "asset-band-2-white",
        }

        logos = build_band_logo_index(records, asset_ids)

        self.assertEqual(
            logos,
            {
                2: {
                    "logoAssetId": "asset-band-2",
                    "whiteLogoAssetId": "asset-band-2-white",
                }
            },
        )

    def test_builds_shared_attribute_and_growth_icon_definitions(self) -> None:
        names = {
            "sp_icon_live_music_type_1": "asset-type-1",
            "sp_icon_live_music_type_2": "asset-type-2",
            "sp_icon_live_music_type_3": "asset-type-3",
            "sp_icon_live_music_type_4": "asset-type-4",
            "sp_icon_live_music_type_5": "asset-type-5",
            "sp_icon_live_music_type_99": "asset-type-all",
            "SP_CardRarityIcon_R": "asset-rarity-r",
            "SP_CardRarityIcon_SR": "asset-rarity-sr",
            "SP_CardRarityIcon_SSR": "asset-rarity-ssr",
            "SP_CardRarityIcon_BD": "asset-rarity-bd",
            "SP_CardRarityIcon_EX": "asset-rarity-ex",
            "Icon_Awakened": "asset-awakened",
            "awakening_base": "asset-awakening-base",
            "IconSpecialTraining": "asset-training",
            "MemberExpIcon": "asset-member-exp",
            "SnapExpIcon": "asset-snap-exp",
        }
        records = [
            {
                "source_file": Path(f"/tmp/{name}.png"),
                "name": name,
            }
            for name in names
        ]
        asset_ids = {
            str(record["source_file"]): names[str(record["name"])]
            for record in records
        }

        taxonomy = build_card_taxonomy(records, asset_ids)

        self.assertEqual(
            [
                (attribute["code"], attribute["names"]["zh-CN"])
                for attribute in taxonomy["attributes"]
            ],
            [
                (1, "红赤"),
                (2, "绀碧"),
                (3, "翡翠"),
                (4, "山吹"),
                (5, "紫苑"),
                (99, "ALL"),
            ],
        )
        self.assertEqual(
            taxonomy["attributes"][2]["iconAssetId"],
            "asset-type-3",
        )
        self.assertEqual(
            taxonomy["growthIcons"],
            {
                "memberLevel": "asset-member-exp",
                "supportLevel": "asset-snap-exp",
                "rank": "asset-training",
                "awake": "asset-awakened",
                "awakeBase": "asset-awakening-base",
            },
        )
        self.assertEqual(
            taxonomy["rarities"],
            [
                {
                    "code": 2,
                    "label": "R",
                    "iconAssetId": "asset-rarity-r",
                },
                {
                    "code": 3,
                    "label": "SR",
                    "iconAssetId": "asset-rarity-sr",
                },
                {
                    "code": 4,
                    "label": "SSR",
                    "iconAssetId": "asset-rarity-ssr",
                },
                {
                    "code": 10,
                    "label": "EX",
                    "iconAssetId": "asset-rarity-ex",
                },
                {
                    "code": 20,
                    "label": "BD",
                    "iconAssetId": "asset-rarity-bd",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
