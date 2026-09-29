"""Finite-state classification for extracted visual resources.

Classification is intentionally path/evidence based. Unknown layouts stay
pending so a new package cannot silently publish a guessed relationship.
"""

from __future__ import annotations

from typing import Any


ENTITY_KINDS = {
    "character",
    "card",
    "item",
    "skill",
    "band_item",
    "stamp",
    "card_taxonomy",
    "band_logo",
}


def _result(
    status: str,
    policy: str,
    reason: str,
    evidence: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "catalogStatus": status,
        "publicPolicy": policy,
        "classificationReason": reason,
        "classificationEvidence": evidence,
        "classificationConfidence": confidence,
    }


def classify_resource(kind: str, container_path: str) -> dict[str, Any]:
    """Classify one extracted resource without inferring unproven entities."""
    if kind in ENTITY_KINDS:
        return _result(
            "identified", "public", "entity_relation", "entity_kind", 1.0
        )

    path = container_path.replace("\\", "/")
    lower = path.lower()
    if "/image/jacket/small/tentative_cover_" in lower or lower.endswith(
        "/jacket_blank.png"
    ):
        return _result(
            "source_placeholder",
            "not_public",
            "unpublished_source_placeholder",
            "container_path_pattern",
            1.0,
        )
    if "/image/jacket/small/jkt_" in lower:
        return _result(
            "archive_only",
            "archive_only",
            "alternate_jacket_derivative",
            "container_path_pattern",
            0.98,
        )
    if "/story/" in lower:
        return _result(
            "archive_only",
            "archive_only",
            "story_artwork",
            "container_path_pattern",
            0.98,
        )
    if "/image/comic/" in lower:
        return _result(
            "archive_only",
            "archive_only",
            "comic_archive",
            "container_path_pattern",
            0.98,
        )
    if "/spot/" in lower and "/spine/" in lower:
        return _result(
            "archive_only",
            "archive_only",
            "scene_source_layer",
            "container_path_pattern",
            0.96,
        )
    archive_patterns = (
        "/membercard/membercommon/",
        "/band/",
        "/image/download/",
        "/image/banner/",
        "/image/carouselhelp/",
        "/image/background/",
        "/image/option/",
    )
    if any(pattern in lower for pattern in archive_patterns):
        return _result(
            "archive_only",
            "archive_only",
            "interface_or_scene_component",
            "container_path_pattern",
            0.94,
        )
    return _result(
        "pending",
        "review_required",
        "unclassified_path",
        "none",
        0.0,
    )
