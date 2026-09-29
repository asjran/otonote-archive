"""Versioned resource acquisition primitives for OUR NOTES."""

from .models import (
    Channel,
    CanonicalEntity,
    CanonicalEvidence,
    ClientBuild,
    ContentRelease,
    EntityVariant,
    GateReason,
    JobCheckpoint,
    JobStatus,
    Region,
    SourceObject,
    VersionVector,
    content_release_id,
)
from .localization import (
    ResolvedLocalizedText,
    extract_localized_text,
    language_coverage,
    resolve_localized_text,
)

__all__ = [
    "Channel",
    "CanonicalEntity",
    "CanonicalEvidence",
    "ClientBuild",
    "ContentRelease",
    "EntityVariant",
    "ResolvedLocalizedText",
    "extract_localized_text",
    "language_coverage",
    "resolve_localized_text",
    "GateReason",
    "JobCheckpoint",
    "JobStatus",
    "Region",
    "SourceObject",
    "VersionVector",
    "content_release_id",
]
