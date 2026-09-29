"""Dataset Query Module — read-only access to ContentRelease query projections.

The module exposes a single ``query(dataset, spec)`` method that:

- resolves the current ContentRelease pointer for ``spec.region`` /
  ``spec.channel``;
- verifies the manifest SHA-256 against ``current.json``;
- loads the requested ``query/<dataset>.json`` projection file;
- verifies the dataset SHA-256 against ``manifest.queryDatasets``;
- applies locale fallback (region default → first non-empty → stable ID);
- applies the ``spec.limit`` / ``spec.cursor`` paging rules (default 20,
  max 100, opaque cursor);
- wraps the resolved projection in a ``DatasetResult`` envelope.

Any integrity failure raises :class:`DatasetIntegrityError` so the HTTP
adapter (T3) can map it to HTTP 503. Valid queries that find no usable
data return HTTP 200 with ``availability=unavailable`` plus a
machine-readable warning.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.contracts import (
    Availability,
    Channel,
    Dataset,
    DatasetResult,
    Freshness,
    Locale,
    Page,
    Provenance,
    QueryIdentity,
    QuerySpec,
    Region,
    ReleaseRef,
    Warning,
    require_utc_timestamp,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DatasetIntegrityError(RuntimeError):
    """Raised when a manifest, pointer, or dataset file fails integrity checks.

    The HTTP adapter maps this to HTTP 503; query responses that simply
    have no data return HTTP 200 with ``availability=unavailable``.
    """


class _ReleaseReadError(RuntimeError):
    """Raised when a published ContentRelease cannot be verified."""


@dataclass(frozen=True)
class _ContentReleaseReader:
    """Minimal read-only implementation of the ContentRelease disk contract."""

    release_root: Path

    def _manifest_path(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
    ) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", content_release_id):
            raise _ReleaseReadError("current release pointer has an invalid release ID")
        if not content_release_id.startswith(
            f"{region.value}-{channel.value}-"
        ):
            raise _ReleaseReadError("current release pointer has the wrong server identity")
        return (
            self.release_root
            / region.value
            / channel.value
            / content_release_id
            / "manifest.json"
        )

    def load_current_release(
        self,
        region: Region,
        channel: Channel,
    ) -> tuple[str, dict[str, Any]] | None:
        pointer_path = self.release_root / region.value / channel.value / "current.json"
        if not pointer_path.is_file():
            return None
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _ReleaseReadError("current release pointer is invalid") from exc
        if not isinstance(pointer, Mapping) or pointer.get("schemaVersion") != 1:
            raise _ReleaseReadError("current release pointer is invalid")
        release_id = pointer.get("contentReleaseId")
        expected_hash = pointer.get("manifestSha256")
        if not isinstance(release_id, str):
            raise _ReleaseReadError("current release pointer is invalid")
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise _ReleaseReadError(
                "current release pointer failed integrity verification"
            )
        manifest_path = self._manifest_path(region, channel, release_id)
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise _ReleaseReadError(
                "current release pointer failed integrity verification"
            ) from exc
        if hashlib.sha256(manifest_bytes).hexdigest() != expected_hash:
            raise _ReleaseReadError(
                "current release pointer failed integrity verification"
            )
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _ReleaseReadError("release manifest is invalid") from exc
        if not isinstance(manifest, dict):
            raise _ReleaseReadError("release manifest is not an object")
        content = manifest.get("contentRelease")
        if (
            not isinstance(content, Mapping)
            or content.get("id") != release_id
            or content.get("region") != region.value
            or content.get("channel") != channel.value
        ):
            raise _ReleaseReadError(
                "current release pointer failed identity verification"
            )
        return release_id, manifest


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


_REGION_DEFAULT_LOCALE: dict[Region, Locale] = {
    Region.GLOBAL: Locale.EN,
}

_LOCALE_FALLBACK_ORDER: tuple[Locale, ...] = (
    Locale.ZH_CN,
    Locale.JA,
    Locale.EN,
    Locale.ZH_TW,
)

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"o": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> int:
    padding = "=" * (-len(value) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cursor is not valid opaque token: {value!r}") from exc
    offset = payload.get("o")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError(f"cursor encodes invalid offset: {value!r}")
    return offset


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetQueryModule:
    """Resolve ``DatasetResult`` envelopes from the on-disk release tree."""

    release_root: Path
    _repository: _ContentReleaseReader = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_repository",
            _ContentReleaseReader(self.release_root),
        )

    # ----- public API ------------------------------------------------------

    def query(self, dataset: Dataset, spec: QuerySpec) -> DatasetResult:
        if not isinstance(dataset, Dataset):
            raise ValueError(f"dataset must be a Dataset enum, got {type(dataset).__name__}")

        if dataset is Dataset.RANKINGS:
            return self._unavailable_rankings(spec)

        resolved = self._resolve_current_release(spec.region, spec.channel)
        if resolved is None:
            return self._no_current_release(spec, dataset)
        content_release_id, manifest = resolved

        descriptor = self._find_descriptor(manifest, dataset)
        if descriptor is None:
            raise DatasetIntegrityError(
                f"manifest {content_release_id} has no queryDatasets entry for {dataset.value}"
            )

        projection = self._load_projection(
            spec.region,
            spec.channel,
            content_release_id,
            descriptor,
        )

        resolved_items, locale_warnings, fallback_used = self._apply_locale_fallback(
            projection.get("items") or [], spec.locale, spec.region
        )

        page_items, next_cursor = self._paginate(
            resolved_items, spec.limit, spec.cursor
        )

        warnings: list[Warning] = []
        for warning in projection.get("warnings") or []:
            if not isinstance(warning, Mapping):
                continue
            code = warning.get("code")
            message = warning.get("message")
            if isinstance(code, str) and isinstance(message, str):
                warnings.append(Warning(code=code, message=message))
        warnings.extend(locale_warnings)

        availability = Availability(projection.get("availability", Availability.UNAVAILABLE.value))
        freshness = Freshness(projection.get("freshness", Freshness.UNKNOWN.value))
        provenance = Provenance(projection.get("provenance", Provenance.UNKNOWN.value))

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        observed_at = projection.get("observedAt")
        expires_at = projection.get("expiresAt")
        if observed_at is not None:
            observed_at = require_utc_timestamp(observed_at, field_name="observedAt")
        if expires_at is not None:
            expires_at = require_utc_timestamp(expires_at, field_name="expiresAt")

        return DatasetResult(
            dataset_schema_version=int(projection.get("datasetSchemaVersion", 1)),
            dataset=dataset,
            query=QueryIdentity(
                region=spec.region.value,
                channel=spec.channel.value,
                locale=spec.locale.value,
            ),
            release=ReleaseRef(
                content_release_id=content_release_id,
                observation_release_id=None,
            ),
            availability=availability,
            freshness=freshness,
            provenance=provenance,
            observed_at=observed_at,
            generated_at=now,
            expires_at=expires_at,
            warnings=tuple(warnings),
            page=Page(limit=min(max(spec.limit or _DEFAULT_LIMIT, 1), _MAX_LIMIT),
                      next_cursor=next_cursor),
            items=tuple(_jsonify_item(item) for item in page_items),
        )

    # ----- resolution helpers ---------------------------------------------

    def _resolve_current_release(
        self, region: Region, channel: Channel
    ) -> tuple[str, dict[str, Any]] | None:
        try:
            return self._repository.load_current_release(region, channel)
        except _ReleaseReadError as exc:
            raise DatasetIntegrityError(str(exc)) from exc

    def _find_descriptor(
        self, manifest: Mapping[str, Any], dataset: Dataset
    ) -> dict[str, Any] | None:
        entries = manifest.get("queryDatasets") or []
        if not isinstance(entries, list):
            raise DatasetIntegrityError("manifest.queryDatasets must be a list")
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("dataset") == dataset.value:
                return dict(entry)
        return None

    def _load_projection(
        self,
        region: Region,
        channel: Channel,
        content_release_id: str,
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        path_value = descriptor.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise DatasetIntegrityError(
                f"queryDatasets entry for {content_release_id} missing path"
            )
        if path_value.startswith("/") or ".." in path_value.split("/"):
            raise DatasetIntegrityError(
                f"queryDatasets entry uses forbidden path: {path_value!r}"
            )
        path = (
            self._repository.release_root
            / region.value
            / channel.value
            / content_release_id
            / path_value
        )
        if not path.is_file():
            raise DatasetIntegrityError(
                f"query dataset file missing: {path}"
            )
        expected_hash = descriptor.get("sha256")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if (
            not isinstance(expected_hash, str)
            or expected_hash != actual_hash
        ):
            raise DatasetIntegrityError(
                f"query dataset {path} failed integrity verification"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatasetIntegrityError(
                f"query dataset {path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise DatasetIntegrityError(
                f"query dataset {path} must be a JSON object"
            )
        schema_version = payload.get("datasetSchemaVersion")
        recorded_version = descriptor.get("datasetSchemaVersion")
        if (
            not isinstance(schema_version, int)
            or not isinstance(recorded_version, int)
            or schema_version != recorded_version
        ):
            raise DatasetIntegrityError(
                f"query dataset {path} schemaVersion mismatch"
            )
        if payload.get("dataset") != descriptor.get("dataset"):
            raise DatasetIntegrityError(
                f"query dataset {path} dataset identifier mismatch"
            )
        return payload

    # ----- locale fallback -------------------------------------------------

    def _apply_locale_fallback(
        self,
        items: Iterable[Any],
        requested: Locale,
        region: Region,
    ) -> tuple[list[dict[str, Any]], list[Warning], bool]:
        region_default = _REGION_DEFAULT_LOCALE[region]
        resolved: list[dict[str, Any]] = []
        warnings: list[Warning] = []
        fallback_used = False
        for item in items:
            if not isinstance(item, Mapping):
                continue
            new_item = dict(item)
            text, used_fallback = self._resolve_localized_text(
                item.get("localizedText"), requested, region_default
            )
            if text is not None:
                new_item["localizedText"] = text
                if used_fallback:
                    fallback_used = True
            resolved.append(new_item)
        if fallback_used:
            warnings.append(
                Warning(
                    code="locale_fallback",
                    message=(
                        "requested locale "
                        f"{requested.value} missing translation; "
                        f"fell back to {region_default.value}"
                    ),
                )
            )
        return resolved, warnings, fallback_used

    @staticmethod
    def _resolve_localized_text(
        value: Any,
        requested: Locale,
        region_default: Locale,
    ) -> tuple[str | None, bool]:
        if not isinstance(value, Mapping):
            return None, False
        # Honor explicit locale first.
        explicit = value.get(requested.value)
        if isinstance(explicit, str) and explicit.strip():
            return explicit, False
        # Region default locale.
        defaulted = value.get(region_default.value)
        if isinstance(defaulted, str) and defaulted.strip():
            return defaulted, True
        # Predefined fallback order.
        for locale in _LOCALE_FALLBACK_ORDER:
            candidate = value.get(locale.value)
            if locale is requested or locale is region_default:
                continue
            if isinstance(candidate, str) and candidate.strip():
                return candidate, True
        # First non-empty string in the map.
        for candidate in value.values():
            if isinstance(candidate, str) and candidate.strip():
                return candidate, True
        return None, False

    # ----- pagination ------------------------------------------------------

    def _paginate(
        self,
        items: Sequence[Mapping[str, Any]],
        requested_limit: int | None,
        cursor: str | None,
    ) -> tuple[list[Mapping[str, Any]], str | None]:
        effective_limit = requested_limit if requested_limit else _DEFAULT_LIMIT
        if effective_limit < 1:
            effective_limit = 1
        if effective_limit > _MAX_LIMIT:
            effective_limit = _MAX_LIMIT
        offset = 0
        if cursor:
            try:
                offset = _decode_cursor(cursor)
            except ValueError as exc:
                raise DatasetIntegrityError(str(exc)) from exc
        end = offset + effective_limit
        page_items = list(items[offset:end])
        next_cursor = _encode_cursor(end) if end < len(items) else None
        return page_items, next_cursor

    # ----- empty-result helpers --------------------------------------------

    def _no_current_release(
        self, spec: QuerySpec, dataset: Dataset
    ) -> DatasetResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return DatasetResult(
            dataset_schema_version=1,
            dataset=dataset,
            query=QueryIdentity(
                region=spec.region.value,
                channel=spec.channel.value,
                locale=spec.locale.value,
            ),
            release=ReleaseRef(
                content_release_id=f"{spec.region.value}-{spec.channel.value}-unpublished",
                observation_release_id=None,
            ),
            availability=Availability.UNAVAILABLE,
            freshness=Freshness.UNKNOWN,
            provenance=Provenance.UNKNOWN,
            observed_at=None,
            generated_at=now,
            expires_at=None,
            warnings=(
                Warning(
                    code="no_current_release",
                    message=(
                        "no ContentRelease has been published for "
                        f"{spec.region.value}/{spec.channel.value}"
                    ),
                ),
            ),
            page=Page(limit=min(max(spec.limit or _DEFAULT_LIMIT, 1), _MAX_LIMIT), next_cursor=None),
            items=(),
        )

    def _unavailable_rankings(self, spec: QuerySpec) -> DatasetResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return DatasetResult(
            dataset_schema_version=1,
            dataset=Dataset.RANKINGS,
            query=QueryIdentity(
                region=spec.region.value,
                channel=spec.channel.value,
                locale=spec.locale.value,
            ),
            release=ReleaseRef(
                content_release_id=f"{spec.region.value}-{spec.channel.value}-unpublished",
                observation_release_id=None,
            ),
            availability=Availability.UNAVAILABLE,
            freshness=Freshness.UNKNOWN,
            provenance=Provenance.UNKNOWN,
            observed_at=None,
            generated_at=now,
            expires_at=None,
            warnings=(
                Warning(
                    code="no_observation",
                    message=(
                        "no ObservationRelease is published for this "
                        "environment yet"
                    ),
                ),
            ),
            page=Page(limit=min(max(spec.limit or _DEFAULT_LIMIT, 1), _MAX_LIMIT), next_cursor=None),
            items=(),
        )


__all__ = ["DatasetIntegrityError", "DatasetQueryModule"]


def _jsonify_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly copy of an item mapping."""
    return json.loads(json.dumps(item, ensure_ascii=False, default=_json_default))


def _json_default(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonify_item(value) for key, value in value.items()}  # type: ignore[arg-type]
    if isinstance(value, (list, tuple)):
        return [_jsonify_item(item) for item in value]
    raise TypeError(f"unsupported item value type: {type(value).__name__}")
