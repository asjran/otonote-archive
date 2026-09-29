"""Stable contracts for the Dynamic Query Service surface.

This module is the only object the rest of the Query Service (T2 ``query.py``,
T3 ``app.py``, T4 ``identity.py``) is allowed to depend on for type identity
and validation. It must remain free of FastAPI, SQLite, or the live release
repository so that downstream modules stay independently testable.

Contracts use camelCase JSON keys in ``to_dict`` / ``from_dict`` to match the
design's public HTTP envelope without leaking Python naming conventions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Mapping


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Region(str, Enum):
    GLOBAL = "global"


class Channel(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class Locale(str, Enum):
    ZH_CN = "zh-CN"
    ZH_TW = "zh-TW"
    JA = "ja"
    EN = "en"


class Dataset(str, Enum):
    EVENTS = "events"
    RANKINGS = "rankings"
    GACHA_POOLS = "gacha-pools"
    SHOPS = "shops"


class Availability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class Provenance(str, Enum):
    CONFIGURED = "configured"
    OBSERVED = "observed"
    HISTORICAL = "historical"
    PREDICTED = "predicted"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    CLAIMED = "claimed"
    VERIFIED = "verified"
    REVOKED = "revoked"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_OFFSET_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def require_utc_timestamp(value: Any, *, field_name: str = "timestamp") -> str:
    """Validate that ``value`` is an ISO-8601 string with explicit timezone.

    Naive timestamps (those ending in neither ``Z`` nor an explicit offset)
    are rejected because callers must always communicate a single, comparable
    moment in time.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    candidate = value.strip()
    if not _OFFSET_PATTERN.match(candidate):
        raise ValueError(
            f"{field_name} must be ISO-8601 with timezone designator: {value!r}"
        )
    # Double-check via datetime parsing to catch edge cases that the regex
    # may accept (e.g. month 13).
    iso_for_parser = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(iso_for_parser)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone: {value!r}")
    return value


def _require_enum(value: Any, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(
            f"{field_name} must be a {enum_type.__name__} enum, "
            f"got {type(value).__name__}"
        )


def _require_non_empty(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")


# ---------------------------------------------------------------------------
# Query side
# ---------------------------------------------------------------------------


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class QuerySpec:
    """The single input parameter for ``DatasetQueryModule.query``."""

    region: Region
    channel: Channel
    locale: Locale
    season_id: str | None = None
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT

    def __post_init__(self) -> None:
        _require_enum(self.region, Region, "region")
        _require_enum(self.channel, Channel, "channel")
        _require_enum(self.locale, Locale, "locale")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ValueError("limit must be an integer")
        if self.limit < 1 or self.limit > MAX_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_LIMIT}, got {self.limit}"
            )
        if self.season_id is not None and not self.season_id.strip():
            raise ValueError("season_id cannot be empty")
        if self.cursor is not None and not self.cursor.strip():
            raise ValueError("cursor cannot be empty")


@dataclass(frozen=True)
class QueryIdentity:
    region: str
    channel: str
    locale: str


@dataclass(frozen=True)
class ReleaseRef:
    content_release_id: str
    observation_release_id: str | None = None


@dataclass(frozen=True)
class Warning:
    code: str
    message: str

    def __post_init__(self) -> None:
        _require_non_empty(self.code, "code")
        _require_non_empty(self.message, "message")


@dataclass(frozen=True)
class Page:
    limit: int
    next_cursor: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ValueError("limit must be an integer")
        if self.limit < 1 or self.limit > MAX_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_LIMIT}, got {self.limit}"
            )
        if self.next_cursor is not None and not self.next_cursor.strip():
            raise ValueError("next_cursor cannot be empty")


@dataclass(frozen=True)
class DatasetResult:
    """The unified query result envelope from design §7."""

    SCHEMA_VERSION: ClassVar[int] = 1

    dataset_schema_version: int
    dataset: Dataset
    query: QueryIdentity
    release: ReleaseRef
    availability: Availability
    freshness: Freshness
    provenance: Provenance
    observed_at: str | None
    generated_at: str
    expires_at: str | None
    warnings: tuple[Warning, ...]
    page: Page
    items: tuple[Any, ...]

    @property
    def schema_version(self) -> int:
        return self.SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_enum(self.dataset, Dataset, "dataset")
        _require_enum(self.availability, Availability, "availability")
        _require_enum(self.freshness, Freshness, "freshness")
        _require_enum(self.provenance, Provenance, "provenance")
        if not isinstance(self.dataset_schema_version, int) or isinstance(
            self.dataset_schema_version, bool
        ):
            raise ValueError("dataset_schema_version must be an integer")
        if self.dataset_schema_version < 1:
            raise ValueError("dataset_schema_version must be >= 1")
        if not isinstance(self.query, QueryIdentity):
            raise ValueError("query must be a QueryIdentity")
        if not isinstance(self.release, ReleaseRef):
            raise ValueError("release must be a ReleaseRef")
        _require_non_empty(self.query.region, "query.region")
        _require_non_empty(self.query.channel, "query.channel")
        _require_non_empty(self.query.locale, "query.locale")
        _require_non_empty(self.release.content_release_id, "release.content_release_id")
        require_utc_timestamp(self.generated_at, field_name="generated_at")
        if self.observed_at is not None:
            require_utc_timestamp(self.observed_at, field_name="observed_at")
        if self.expires_at is not None:
            require_utc_timestamp(self.expires_at, field_name="expires_at")
        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple of Warning")
        for index, warning in enumerate(self.warnings):
            if not isinstance(warning, Warning):
                raise ValueError(f"warnings[{index}] must be a Warning")
        if not isinstance(self.page, Page):
            raise ValueError("page must be a Page")
        if not isinstance(self.items, tuple):
            raise ValueError("items must be a tuple")

    # ----- serialization ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "datasetSchemaVersion": self.dataset_schema_version,
            "dataset": self.dataset.value,
            "query": {
                "region": self.query.region,
                "channel": self.query.channel,
                "locale": self.query.locale,
            },
            "release": {
                "contentReleaseId": self.release.content_release_id,
                "observationReleaseId": self.release.observation_release_id,
            },
            "availability": self.availability.value,
            "freshness": self.freshness.value,
            "provenance": self.provenance.value,
            "observedAt": self.observed_at,
            "generatedAt": self.generated_at,
            "expiresAt": self.expires_at,
            "warnings": [
                {"code": warning.code, "message": warning.message}
                for warning in self.warnings
            ],
            "page": {
                "limit": self.page.limit,
                "nextCursor": self.page.next_cursor,
            },
            "items": [self._serialize_item(item) for item in self.items],
        }

    @staticmethod
    def _serialize_item(item: Any) -> Any:
        if hasattr(item, "to_dict"):
            return item.to_dict()
        if isinstance(item, Mapping):
            return {key: DatasetResult._serialize_item(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [DatasetResult._serialize_item(value) for value in item]
        return item

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DatasetResult":
        if not isinstance(payload, Mapping):
            raise ValueError("DatasetResult payload must be a mapping")
        schema_version = payload.get("schemaVersion")
        if schema_version != cls.SCHEMA_VERSION:
            raise ValueError(
                f"unsupported DatasetResult schemaVersion: {schema_version!r}"
            )
        query = payload.get("query") or {}
        release = payload.get("release") or {}
        return cls(
            dataset_schema_version=int(payload["datasetSchemaVersion"]),
            dataset=Dataset(payload["dataset"]),
            query=QueryIdentity(
                region=str(query["region"]),
                channel=str(query["channel"]),
                locale=str(query["locale"]),
            ),
            release=ReleaseRef(
                content_release_id=str(release["contentReleaseId"]),
                observation_release_id=(
                    None
                    if release.get("observationReleaseId") is None
                    else str(release["observationReleaseId"])
                ),
            ),
            availability=Availability(payload["availability"]),
            freshness=Freshness(payload["freshness"]),
            provenance=Provenance(payload["provenance"]),
            observed_at=(
                None
                if payload.get("observedAt") is None
                else str(payload["observedAt"])
            ),
            generated_at=str(payload["generatedAt"]),
            expires_at=(
                None
                if payload.get("expiresAt") is None
                else str(payload["expiresAt"])
            ),
            warnings=tuple(
                Warning(code=str(item["code"]), message=str(item["message"]))
                for item in payload.get("warnings") or ()
            ),
            page=Page(
                limit=int(payload["page"]["limit"]),
                next_cursor=(
                    None
                    if payload["page"].get("nextCursor") is None
                    else str(payload["page"]["nextCursor"])
                ),
            ),
            items=tuple(payload.get("items") or ()),
        )


# ---------------------------------------------------------------------------
# Binding side
# ---------------------------------------------------------------------------


_IDENTITY_NAMESPACE_PREFIXES = ("qq-official:", "onebot:")
_ENVIRONMENT_PATTERN = re.compile(r"^global-(staging|production)$")


def _require_identity_namespace(value: Any, field_name: str) -> None:
    _require_non_empty(value, field_name)
    if not isinstance(value, str) or not any(
        value.startswith(prefix) for prefix in _IDENTITY_NAMESPACE_PREFIXES
    ):
        raise ValueError(
            f"{field_name} must start with one of "
            f"{', '.join(_IDENTITY_NAMESPACE_PREFIXES)}; got {value!r}"
        )


def _require_game_environment_id(value: Any, field_name: str) -> None:
    _require_non_empty(value, field_name)
    if not isinstance(value, str) or not _ENVIRONMENT_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must look like '<region>-<channel>' "
            "(e.g. 'global-production'); got " + repr(value)
        )


@dataclass(frozen=True)
class Principal:
    adapter_id: str
    identity_namespace: str
    platform_user_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.adapter_id, "adapter_id")
        _require_identity_namespace(self.identity_namespace, "identity_namespace")
        _require_non_empty(self.platform_user_id, "platform_user_id")


@dataclass(frozen=True)
class BindingInput:
    identity_namespace: str
    platform_user_id: str
    game_environment_id: str
    game_account_id: str

    def __post_init__(self) -> None:
        _require_identity_namespace(self.identity_namespace, "identity_namespace")
        _require_non_empty(self.platform_user_id, "platform_user_id")
        _require_game_environment_id(self.game_environment_id, "game_environment_id")
        _require_non_empty(self.game_account_id, "game_account_id")


@dataclass(frozen=True)
class Binding:
    id: str
    identity_namespace: str
    platform_user_id: str
    game_environment_id: str
    game_account_id: str
    verification_status: VerificationStatus
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _require_non_empty(self.id, "id")
        _require_identity_namespace(self.identity_namespace, "identity_namespace")
        _require_non_empty(self.platform_user_id, "platform_user_id")
        _require_game_environment_id(self.game_environment_id, "game_environment_id")
        _require_non_empty(self.game_account_id, "game_account_id")
        _require_enum(self.verification_status, VerificationStatus, "verification_status")
        require_utc_timestamp(self.created_at, field_name="created_at")
        require_utc_timestamp(self.updated_at, field_name="updated_at")

    # ----- redacted logging surface ----------------------------------------

    def summary(self) -> dict[str, str]:
        """Return a log-friendly summary without leaking full identifiers."""

        return {
            "bindingId": self.id,
            "identityNamespace": self.identity_namespace,
            "platformUserDigest": _short_digest(self.platform_user_id),
            "gameAccountDigest": _short_digest(self.game_account_id),
            "gameEnvironmentId": self.game_environment_id,
            "verificationStatus": self.verification_status.value,
        }


def _short_digest(value: str) -> str:
    payload = value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


__all__ = [
    "Availability",
    "Binding",
    "BindingInput",
    "Channel",
    "Dataset",
    "DatasetResult",
    "Freshness",
    "Locale",
    "Page",
    "Principal",
    "Provenance",
    "QueryIdentity",
    "QuerySpec",
    "Region",
    "ReleaseRef",
    "VerificationStatus",
    "Warning",
    "require_utc_timestamp",
]
