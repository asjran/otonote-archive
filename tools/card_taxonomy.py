"""Build the shared card/music taxonomy from verified UI assets."""

from __future__ import annotations

import re
from typing import Any, Iterable


class CardTaxonomyError(ValueError):
    """Raised when a functional taxonomy asset is missing or ambiguous."""


ATTRIBUTE_DEFINITIONS = (
    {
        "code": 1,
        "names": {
            "zh-CN": "红赤",
            "zh-TW": "紅赤",
            "ja": "紅赤タイプ",
            "en": "Red",
        },
        "color": "#E85B78",
    },
    {
        "code": 2,
        "names": {
            "zh-CN": "绀碧",
            "zh-TW": "紺碧",
            "ja": "紺碧タイプ",
            "en": "Azure",
        },
        "color": "#5C91DC",
    },
    {
        "code": 3,
        "names": {
            "zh-CN": "翡翠",
            "zh-TW": "翡翠",
            "ja": "翡翠タイプ",
            "en": "Jade",
        },
        "color": "#4DAF83",
    },
    {
        "code": 4,
        "names": {
            "zh-CN": "山吹",
            "zh-TW": "山吹",
            "ja": "山吹タイプ",
            "en": "Golden Yellow",
        },
        "color": "#D7A83E",
    },
    {
        "code": 5,
        "names": {
            "zh-CN": "紫苑",
            "zh-TW": "紫苑",
            "ja": "紫苑タイプ",
            "en": "Purple",
        },
        "color": "#8F68C8",
    },
    {
        "code": 99,
        "names": {
            "zh-CN": "ALL",
            "zh-TW": "ALL",
            "ja": "ALL",
            "en": "ALL",
        },
        "color": "#747C91",
    },
)

GROWTH_ICON_NAMES = {
    "memberLevel": "memberexpicon",
    "supportLevel": "snapexpicon",
    "rank": "iconspecialtraining",
    "awake": "icon_awakened",
    "awakeBase": "awakening_base",
}

RARITY_DEFINITIONS = (
    {"code": 2, "label": "R", "iconName": "sp_cardrarityicon_r"},
    {"code": 3, "label": "SR", "iconName": "sp_cardrarityicon_sr"},
    {"code": 4, "label": "SSR", "iconName": "sp_cardrarityicon_ssr"},
    # App.Master.CardRarity in the Global 1.0.1 metadata defines EX=10, BD=20.
    {"code": 10, "label": "EX", "iconName": "sp_cardrarityicon_ex"},
    {"code": 20, "label": "BD", "iconName": "sp_cardrarityicon_bd"},
)

BAND_LOGO_PATTERN = re.compile(
    r"^Assets/AddressableResources/Band/(?P<band_id>\d+)/"
    r"band_logo(?P<white>_white)?\.png$",
    re.IGNORECASE,
)

# Global 1.0.1 uses these sprite names in its embedded UI atlas. Keep the
# source names intact in manifests; normalize only at the taxonomy boundary.
FUNCTIONAL_ICON_ALIASES = {
    "sp_icon_member_card_type_2": "sp_icon_live_music_type_2",
    "specialtraining": "iconspecialtraining",
    **{f"rarityiconcenter_{label}": f"sp_cardrarityicon_{label}"
       for label in ("r", "sr", "ssr", "bd", "ex")},
}


def _asset_ids_by_name(
    records: Iterable[dict[str, Any]],
    asset_ids: dict[str, str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for record in records:
        source_file = str(record.get("source_file", ""))
        asset_id = asset_ids.get(source_file)
        name = str(record.get("name", "")).lower()
        if not name or not asset_id:
            continue
        existing = values.get(name)
        if existing is not None and existing != asset_id:
            raise CardTaxonomyError(
                f"ambiguous functional asset name: {name}"
            )
        values[name] = asset_id
    for source_name, canonical_name in FUNCTIONAL_ICON_ALIASES.items():
        if source_name in values:
            values.setdefault(canonical_name, values[source_name])
    return values


def build_card_taxonomy(
    records: Iterable[dict[str, Any]],
    asset_ids: dict[str, str],
) -> dict[str, Any]:
    """Return complete attribute and growth icon definitions."""

    by_name = _asset_ids_by_name(records, asset_ids)
    attributes = []
    for definition in ATTRIBUTE_DEFINITIONS:
        code = int(definition["code"])
        icon_name = f"sp_icon_live_music_type_{code}"
        icon_asset_id = by_name.get(icon_name)
        if icon_asset_id is None:
            raise CardTaxonomyError(
                f"missing functional attribute icon: {icon_name}"
            )
        attributes.append(
            {
                **definition,
                "iconAssetId": icon_asset_id,
            }
        )

    growth_icons = {}
    for key, name in GROWTH_ICON_NAMES.items():
        asset_id = by_name.get(name)
        if asset_id is None:
            raise CardTaxonomyError(
                f"missing functional growth icon: {name}"
            )
        growth_icons[key] = asset_id

    rarities = []
    for definition in RARITY_DEFINITIONS:
        icon_name = str(definition["iconName"])
        icon_asset_id = by_name.get(icon_name)
        if icon_asset_id is None:
            raise CardTaxonomyError(
                f"missing functional rarity icon: {icon_name}"
            )
        rarities.append(
            {
                "code": int(definition["code"]),
                "label": str(definition["label"]),
                "iconAssetId": icon_asset_id,
            }
        )

    return {
        "attributes": attributes,
        "rarities": rarities,
        "growthIcons": growth_icons,
    }


def build_band_logo_index(
    records: Iterable[dict[str, Any]],
    asset_ids: dict[str, str],
) -> dict[int, dict[str, str]]:
    """Index verified normal and inverse band logos by Master band ID."""

    values: dict[int, dict[str, str]] = {}
    for record in records:
        match = BAND_LOGO_PATTERN.fullmatch(
            str(record.get("container_path", ""))
        )
        if match is None:
            continue
        asset_id = asset_ids.get(str(record.get("source_file", "")))
        if asset_id is None:
            continue
        band_id = int(match.group("band_id"))
        key = "whiteLogoAssetId" if match.group("white") else "logoAssetId"
        current = values.setdefault(band_id, {})
        existing = current.get(key)
        if existing is not None and existing != asset_id:
            raise CardTaxonomyError(
                f"ambiguous {key} for band {band_id}"
            )
        current[key] = asset_id
    return values
