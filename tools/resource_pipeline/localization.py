"""One locale-preserving interface for MasterText projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


LOCALE_FIELDS = {
    "zh-CN": "_simplifiedChinese",
    "zh-TW": "_traditionalChinese",
    "ja": "_japanese",
    "en": "_english",
}
SUPPORTED_LOCALES = tuple(LOCALE_FIELDS)
LEGACY_DISPLAY_LOCALE = "zh-CN"
DEFAULT_FALLBACK_ORDER = ("zh-CN", "ja", "en", "zh-TW")


@dataclass(frozen=True)
class ResolvedLocalizedText:
    text: str
    requested_locale: str
    actual_locale: str | None
    used_fallback: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "requestedLocale": self.requested_locale,
            "actualLocale": self.actual_locale,
            "usedFallback": self.used_fallback,
        }


def extract_localized_text(row: Mapping[str, Any] | None) -> dict[str, str]:
    """Retain every non-empty supported language from one MasterText row."""
    if not row:
        return {}
    localized: dict[str, str] = {}
    for locale, field in LOCALE_FIELDS.items():
        raw = row.get(field)
        if isinstance(raw, str) and raw.strip():
            localized[locale] = raw.strip()
    return localized


def _normalized_values(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not value:
        return {}
    if any(field in value for field in LOCALE_FIELDS.values()):
        return extract_localized_text(value)
    return {
        locale: raw.strip()
        for locale, raw in value.items()
        if locale in SUPPORTED_LOCALES
        and isinstance(raw, str)
        and raw.strip()
    }


def resolve_localized_text(
    value: Mapping[str, Any] | None,
    requested_locale: str = LEGACY_DISPLAY_LOCALE,
    fallback: str = "",
    fallback_order: Sequence[str] = DEFAULT_FALLBACK_ORDER,
) -> ResolvedLocalizedText:
    """Resolve display text without discarding its actual source locale."""
    if requested_locale not in SUPPORTED_LOCALES:
        raise ValueError(f"unsupported locale: {requested_locale}")
    values = _normalized_values(value)
    candidates = (requested_locale,) + tuple(
        locale
        for locale in fallback_order
        if locale != requested_locale and locale in SUPPORTED_LOCALES
    )
    for locale in candidates:
        text = values.get(locale)
        if text:
            return ResolvedLocalizedText(
                text=text,
                requested_locale=requested_locale,
                actual_locale=locale,
                used_fallback=locale != requested_locale,
            )
    return ResolvedLocalizedText(
        text=fallback,
        requested_locale=requested_locale,
        actual_locale=None,
        used_fallback=bool(fallback),
    )


def resolve_text(
    value: Mapping[str, Any] | None,
    fallback: str = "",
    locale: str = LEGACY_DISPLAY_LOCALE,
) -> str:
    """Compatibility displayName interface backed by locale-aware resolution."""
    return resolve_localized_text(value, locale, fallback).text


def language_coverage(
    values: Iterable[Mapping[str, Any]],
    requested_locale: str,
) -> dict[str, Any]:
    rows = [_normalized_values(value) for value in values]
    resolved = [
        resolve_localized_text(value, requested_locale) for value in rows
    ]
    return {
        "requestedLocale": requested_locale,
        "total": len(rows),
        "availableByLocale": {
            locale: sum(locale in value for value in rows)
            for locale in SUPPORTED_LOCALES
        },
        "fallbackCount": sum(item.used_fallback for item in resolved),
        "missingCount": sum(not item.text for item in resolved),
    }
