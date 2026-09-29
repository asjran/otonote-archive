"""Region-isolated entity variants and evidence-only canonical links."""

from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

from .localization import resolve_localized_text
from .models import (
    CanonicalEntity,
    CanonicalEvidence,
    Channel,
    EntityVariant,
    Region,
)


def variant_ref(variant: EntityVariant) -> str:
    return ":".join(
        (
            variant.region.value,
            variant.channel.value,
            variant.entity_type,
            variant.source_master_id,
            variant.first_seen_content_release,
        )
    )


def project_variants(
    variants: Iterable[EntityVariant],
    region: Region,
    channel: Channel,
    locale: str,
) -> list[dict[str, object]]:
    """Project only variants belonging to the requested server identity."""
    projected: list[dict[str, object]] = []
    for variant in variants:
        if variant.region != region or variant.channel != channel:
            continue
        localized = variant.localized_text_dict()
        resolved = resolve_localized_text(localized, locale)
        projected.append(
            {
                "variantRef": variant_ref(variant),
                "entityType": variant.entity_type,
                "sourceMasterId": variant.source_master_id,
                "region": variant.region.value,
                "channel": variant.channel.value,
                "contentReleaseId": variant.last_seen_content_release,
                "availability": variant.availability,
                "localizedText": localized,
                "displayText": resolved.as_dict(),
                "assetRelations": list(variant.asset_relations),
                "sourceEvidence": list(variant.source_evidence),
            }
        )
    return sorted(projected, key=lambda item: str(item["variantRef"]))


def canonicalize_variants(
    variants: Sequence[EntityVariant],
    evidence: Sequence[CanonicalEvidence],
    *,
    verified_business_fields: bool = True,
) -> CanonicalEntity | None:
    """Create a canonical link only from explicit admissible evidence."""
    refs = tuple(variant_ref(variant) for variant in variants)
    if len(set(refs)) < 2 or not evidence:
        return None
    kinds = {item.kind for item in evidence}
    if kinds == {"matchingAssetSha256"} and not verified_business_fields:
        return None
    digest = hashlib.sha256("\n".join(sorted(refs)).encode("utf-8")).hexdigest()
    return CanonicalEntity(
        id=f"canonical-{digest[:16]}",
        variant_refs=refs,
        evidence=tuple(evidence),
    )
