"""Build the public BandItem enhancement ledger from verified Master data."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class BandItemError(ValueError):
    """Raised when BandItem inputs violate publishing invariants."""


@dataclass(frozen=True)
class BandItemBuild:
    database: dict[str, Any]
    quality_report: dict[str, Any]
    warnings: list[str]


REQUIRED_TABLES = (
    "MasterText",
    "MasterBand",
    "MasterBandItem",
    "MasterBandItemLevel",
    "MasterBandItemSkillEffect",
    "MasterSkillEffectSetting",
    "MasterSkillTarget",
)


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise BandItemError(f"missing Master table: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BandItemError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise BandItemError(f"{name} must contain an _allData array")
    return rows


def _unique_index(
    rows: Iterable[dict[str, Any]],
    field: str,
    label: str,
) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, (int, str)):
            raise BandItemError(f"{label} row has invalid {field}: {key!r}")
        if key in result:
            raise BandItemError(f"duplicate {label} {field}: {key}")
        result[key] = row
    return result


def _resolve_text(
    texts: Mapping[str, dict[str, Any]],
    text_id: Any,
    fallback: str,
) -> str:
    row = texts.get(text_id) if isinstance(text_id, str) else None
    if row:
        for field in (
            "_simplifiedChinese",
            "_japanese",
            "_english",
            "_traditionalChinese",
        ):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _format_percent(raw_value: int) -> str:
    value = raw_value / 100
    return f"{value:g}%"


def _render_summary(template: str, raw_value: int | None) -> str:
    rendered = re.sub(r"<style=[^>]+>", "", template)
    rendered = rendered.replace("</style>", "")
    if raw_value is not None:
        rendered = rendered.replace("{0}", f"{raw_value / 100:g}")
    return rendered.strip()


def _asset_by_container(
    assets: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for asset in assets:
        container = asset.get("containerPath")
        if isinstance(container, str) and container:
            result[container] = asset
    return result


def build_band_items(
    master_root: Path,
    release_id: str,
    assets: Iterable[Mapping[str, Any]] = (),
) -> BandItemBuild:
    """Return a deterministic enhancement database from a Master directory."""

    tables = {
        name: _load_table(master_root, name) for name in REQUIRED_TABLES
    }
    texts = _unique_index(tables["MasterText"], "_id", "MasterText")
    bands = _unique_index(tables["MasterBand"], "_id", "MasterBand")
    band_items = _unique_index(
        tables["MasterBandItem"], "_id", "MasterBandItem"
    )
    targets = _unique_index(
        tables["MasterSkillTarget"], "_id", "MasterSkillTarget"
    )
    effect_settings = {
        int(row["_skillEffectType"]): row
        for row in tables["MasterSkillEffectSetting"]
        if isinstance(row.get("_skillEffectType"), int)
    }

    levels_by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_level_keys: set[tuple[int, int]] = set()
    for row in tables["MasterBandItemLevel"]:
        item_id = row.get("_bandItemId")
        level = row.get("_level")
        if not isinstance(item_id, int) or item_id not in band_items:
            raise BandItemError(
                f"BandItem level references unknown item: {item_id!r}"
            )
        if not isinstance(level, int) or level < 1:
            raise BandItemError(f"BandItem level is invalid: {level!r}")
        key = (item_id, level)
        if key in seen_level_keys:
            raise BandItemError(
                f"duplicate BandItem level: item={item_id}, level={level}"
            )
        seen_level_keys.add(key)
        levels_by_item[item_id].append(row)

    effects_by_level: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    max_level_by_item = {
        item_id: max(int(row["_level"]) for row in rows)
        for item_id, rows in levels_by_item.items()
    }
    future_effects_by_item: dict[int, int] = defaultdict(int)
    seen_effect_ids: set[int] = set()
    for row in tables["MasterBandItemSkillEffect"]:
        source_id = row.get("_id")
        item_id = row.get("_bandItemId")
        level = row.get("_level")
        if not isinstance(source_id, int) or source_id in seen_effect_ids:
            raise BandItemError(f"invalid or duplicate BandItem effect: {source_id!r}")
        seen_effect_ids.add(source_id)
        if not isinstance(item_id, int) or item_id not in band_items:
            raise BandItemError(
                f"BandItem effect references unknown item: {item_id!r}"
            )
        if isinstance(level, int) and level > max_level_by_item.get(item_id, 0):
            future_effects_by_item[item_id] += 1
            continue
        if not isinstance(level, int) or (item_id, level) not in seen_level_keys:
            raise BandItemError(
                f"BandItem effect references unknown level: item={item_id}, "
                f"level={level!r}"
            )
        effects_by_level[(item_id, level)].append(row)

    assets_by_container = _asset_by_container(assets)
    # Band items share the skill-level resource table; _level is the target level.
    material_items = _unique_index(
        _load_table(master_root, "MasterItem"), "_id", "MasterItem"
    ) if (master_root / "MasterItem.json").is_file() else {}
    resource_rows = _load_table(master_root, "MasterSkillLevelResource") if (
        master_root / "MasterSkillLevelResource.json"
    ).is_file() else []
    resource_groups = {row.get("_resourceGroupId") for row in band_items.values()}
    materials_by_level: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    seen_material_keys: set[tuple[int, int, int]] = set()
    for resource in resource_rows:
        group = resource.get("_group")
        if group not in resource_groups:
            continue
        level = resource.get("_level")
        item_id = resource.get("_itemID")
        amount = resource.get("_count")
        if (type(level) is not int or level < 1 or type(item_id) is not int
                or item_id not in material_items or type(amount) is not int or amount < 0):
            raise BandItemError(f"invalid BandItem material resource: {resource!r}")
        key = (group, level, item_id)
        if key in seen_material_keys:
            raise BandItemError(f"duplicate BandItem material resource: {key}")
        seen_material_keys.add(key)
        material = material_items[item_id]
        material_asset = assets_by_container.get(
            f"Assets/AddressableResources/{material.get('_imagePath')}.png"
        )
        materials_by_level[(group, level)].append({
            "itemId": f"item-{item_id}",
            "name": _resolve_text(texts, material.get("_nameTextId"), f"道具 {item_id}"),
            "amount": amount,
            "previewUrl": material_asset.get("previewUrl") if material_asset else None,
            "sourceResourceId": resource["_id"],
        })
    warnings: list[str] = []
    for item_id, count in sorted(future_effects_by_item.items()):
        warnings.append(
            f"BandItem {item_id} has {count} effects beyond current level cap "
            f"{max_level_by_item[item_id]}; future effects remain unprojected"
        )
    records: list[dict[str, Any]] = []

    for master_id, row in band_items.items():
        if not isinstance(master_id, int):
            raise BandItemError(f"BandItem id must be numeric: {master_id!r}")
        band_id = row.get("_bandId")
        if not isinstance(band_id, int) or band_id not in bands:
            raise BandItemError(
                f"BandItem {master_id} references unknown band: {band_id!r}"
            )
        band = bands[band_id]
        band_name = _resolve_text(
            texts,
            band.get("_nameTextID"),
            f"乐队 {band_id}",
        )
        template = _resolve_text(
            texts,
            row.get("_descriptionTextId"),
            "效果值 {0}%",
        )
        container = (
            "Assets/AddressableResources/Band/"
            f"{band_id}/BandItem/{master_id}/band_item.png"
        )
        asset = assets_by_container.get(container)

        source_levels = sorted(
            levels_by_item.get(master_id, []),
            key=lambda value: int(value["_level"]),
        )
        actual_levels = [int(value["_level"]) for value in source_levels]
        if actual_levels != list(range(1, max(actual_levels, default=0) + 1)):
            warnings.append(
                f"BandItem {master_id} has non-contiguous levels {actual_levels}"
            )

        levels: list[dict[str, Any]] = []
        item_partial = False
        for level_row in source_levels:
            level = int(level_row["_level"])
            effects: list[dict[str, Any]] = []
            for effect in sorted(
                effects_by_level.get((master_id, level), []),
                key=lambda value: int(value["_id"]),
            ):
                effect_type = int(effect.get("_skillEffectType") or 0)
                raw_value = int(effect.get("_effectValue") or 0)
                target_master_ids = [
                    int(value)
                    for value in effect.get("_skillTargetIDs") or []
                    if isinstance(value, int)
                ]
                target_band_ids: list[str] = []
                effect_partial = False
                for target_id in target_master_ids:
                    target = targets.get(target_id)
                    if target is None:
                        effect_partial = True
                        continue
                    target_band_id = int(target.get("_bandID") or 0)
                    if target_band_id:
                        target_band_ids.append(f"band-{target_band_id}")
                setting = effect_settings.get(effect_type)
                if setting is None:
                    effect_partial = True
                    effect_name = f"效果类型 {effect_type}"
                else:
                    effect_name = _resolve_text(
                        texts,
                        setting.get("_nameTextId"),
                        f"效果类型 {effect_type}",
                    )
                item_partial = item_partial or effect_partial
                effects.append(
                    {
                        "sourceEffectId": int(effect["_id"]),
                        "effectType": effect_type,
                        "effectName": effect_name,
                        "rawValue": raw_value,
                        "displayValue": _format_percent(raw_value),
                        "targetMasterIds": target_master_ids,
                        "targetBandIds": sorted(set(target_band_ids)),
                        "interpretationStatus": (
                            "partial" if effect_partial else "identified"
                        ),
                    }
                )

            if not effects:
                item_partial = True
                warnings.append(
                    f"BandItem {master_id} level {level} has no effects"
                )
            primary_value = effects[0]["rawValue"] if effects else None
            materials = materials_by_level.get((row.get("_resourceGroupId"), level))
            if materials is None:
                warnings.append(f"BandItem {master_id} level {level} has no material resources")
            levels.append(
                {
                    "level": level,
                    "playerRank": int(level_row.get("_playerRank") or 0),
                    "renderedSummary": _render_summary(template, primary_value),
                    "effects": effects,
                    "upgradeMaterials": (
                        sorted(materials, key=lambda value: value["sourceResourceId"])
                        if materials is not None else None
                    ),
                }
            )

        records.append(
            {
                "id": f"band-item-{master_id}",
                "masterId": master_id,
                "name": _resolve_text(
                    texts,
                    row.get("_nameTextId"),
                    f"乐队物件 {master_id}",
                ),
                "descriptionTemplate": template,
                "bandId": f"band-{band_id}",
                "bandName": band_name,
                "resourceGroupId": int(row.get("_resourceGroupId") or 0),
                "displayOrder": int(row.get("_displayOrder") or 0),
                "assetId": asset.get("id") if asset else None,
                "previewUrl": asset.get("previewUrl") if asset else None,
                "containerPath": container,
                "catalogStatus": "identified" if asset else "missing_asset",
                "levels": levels,
                "interpretationStatus": "partial" if item_partial else "identified",
                "sourceReleaseIds": [release_id],
            }
        )

    records.sort(
        key=lambda value: (
            int(value["bandId"].split("-")[-1]),
            int(value["displayOrder"]),
            int(value["masterId"]),
        )
    )
    band_records = []
    for master_id, row in sorted(bands.items()):
        if not isinstance(master_id, int):
            continue
        band_records.append(
            {
                "id": f"band-{master_id}",
                "masterId": master_id,
                "name": _resolve_text(
                    texts,
                    row.get("_nameTextID"),
                    f"乐队 {master_id}",
                ),
                "mainColor": str(row.get("_mainColorCode") or "#222222"),
                "subColor": str(row.get("_subColorCode") or "#FFFFFF"),
                "itemIds": [
                    item["id"]
                    for item in records
                    if item["bandId"] == f"band-{master_id}"
                ],
            }
        )

    quality = {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "bandCount": len(band_records),
        "itemCount": len(records),
        "levelCount": sum(len(item["levels"]) for item in records),
        "effectCount": sum(
            len(level["effects"])
            for item in records
            for level in item["levels"]
        ),
        "futureEffectCount": sum(future_effects_by_item.values()),
        "missingAssetCount": sum(
            item["catalogStatus"] == "missing_asset" for item in records
        ),
        "partialItemCount": sum(
            item["interpretationStatus"] == "partial" for item in records
        ),
        "warnings": warnings,
    }
    database = {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "bands": band_records,
        "items": records,
        "quality": quality,
    }
    return BandItemBuild(database, quality, warnings)
