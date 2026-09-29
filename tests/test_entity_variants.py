from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.entity_projection import (
    canonicalize_variants,
    project_variants,
    variant_ref,
)
from tools.resource_pipeline.models import (
    CanonicalEvidence,
    Channel,
    EntityVariant,
    Region,
)


def variant(region: Region, master_id: str, name: str) -> EntityVariant:
    release_id = f"{region.value}-staging-fixture"
    return EntityVariant(
        entity_type="music",
        region=region,
        channel=Channel.STAGING,
        source_master_id=master_id,
        first_seen_content_release=release_id,
        last_seen_content_release=release_id,
        availability="available",
        localized_text=(("ja", name),),
    )


class EntityVariantProjectionTest(unittest.TestCase):
    def test_locale_switch_does_not_change_region(self) -> None:
        variants = [
            variant(Region.GLOBAL, "10", "同名"),
            variant(Region.GLOBAL, "10", "同名"),
        ]

        japanese = project_variants(
            variants, Region.GLOBAL, Channel.STAGING, "ja"
        )
        english = project_variants(
            variants, Region.GLOBAL, Channel.STAGING, "en"
        )

        self.assertEqual(japanese[0]["region"], "global")
        self.assertEqual(english[0]["region"], "global")
        self.assertEqual(japanese[0]["variantRef"], english[0]["variantRef"])

    def test_missing_entity_is_not_copied_from_another_channel(self) -> None:
        variants = [variant(Region.GLOBAL, "99", "Global only")]

        self.assertEqual(
            project_variants(
                variants, Region.GLOBAL, Channel.PRODUCTION, "zh-CN"
            ),
            [],
        )

    def test_same_name_and_similar_id_do_not_create_canonical_entity(self) -> None:
        jp = variant(Region.GLOBAL, "100", "Same")
        global_variant = variant(Region.GLOBAL, "101", "Same")

        self.assertIsNone(canonicalize_variants([jp, global_variant], ()))

    def test_matching_hash_with_conflicting_business_fields_stays_distinct(self) -> None:
        jp = variant(Region.GLOBAL, "100", "JP")
        global_variant = variant(Region.GLOBAL, "200", "Global")
        evidence = (
            CanonicalEvidence("matchingAssetSha256", "a" * 64),
        )

        self.assertIsNone(
            canonicalize_variants(
                [jp, global_variant],
                evidence,
                verified_business_fields=False,
            )
        )

    def test_manual_confirmation_is_retained_as_evidence(self) -> None:
        jp = variant(Region.GLOBAL, "100", "JP")
        global_variant = variant(Region.GLOBAL, "200", "Global")
        evidence = (CanonicalEvidence("manualConfirmation", "operator-42"),)

        canonical = canonicalize_variants([jp, global_variant], evidence)

        self.assertIsNotNone(canonical)
        assert canonical is not None
        self.assertEqual(canonical.evidence, evidence)
        self.assertEqual(
            canonical.variant_refs,
            (variant_ref(jp), variant_ref(global_variant)),
        )


if __name__ == "__main__":
    unittest.main()
