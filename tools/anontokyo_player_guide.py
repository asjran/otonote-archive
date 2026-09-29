"""Project the private AnonTokyo evidence model into player-facing guide data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
STUDIO_SCHEMA_VERSION = 2
MAX_SCENE_STATIC_IMAGE_KEYS = 4
OUTPUT_FILES = (
    "store.json",
    "growth.json",
    "goods.json",
    "customers.json",
    "wardrobe.json",
    "inspiration.json",
    "furniture.json",
    "themes.json",
    "stages.json",
    "chats.json",
    "tasks.json",
    "staff.json",
    "guide.json",
    "mechanics.json",
)
FORBIDDEN_KEYS = {
    "sourceTable",
    "sourceId",
    "sourceFields",
    "sourceTables",
    "interpretationStatus",
    "warnings",
    "abilityId",
    "taskTypeId",
    "taskTabId",
    "categoryId",
    "tagIds",
    "predecessorTaskId",
    "rewardRaw",
    "passiveAbilitiesRaw",
    "identityNumber",
    "charactersByCanUse",
    "charactersByPath",
    "characterAttributionStatus",
    "frameType",
    "hintText",
    "carouselId",
}
VERIFIED_FORMULA_POLICY = {
    "purchaseCost": "per_unit",
    "saleCoin": "per_unit",
    "deliveryDuration": "seconds_per_batch",
    "batchSize": "purchase_item_count",
}
RAW_TEXT_KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}$")
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class AnonTokyoPlayerGuideError(RuntimeError):
    """Raised when player-facing guide data cannot be built safely."""


@dataclass(frozen=True)
class AnonTokyoPlayerGuideResult:
    output_root: Path
    manifest: Mapping[str, Any]
    report: Mapping[str, Any]
    files: tuple[Path, ...]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnonTokyoPlayerGuideError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise AnonTokyoPlayerGuideError(f"{label} must be an object")
    return value


def _load_projection(projection_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = _read_json(projection_root / "manifest.json", label="projection manifest")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise AnonTokyoPlayerGuideError("projection manifest has no file index")
    required = (
        "goods.json",
        "decorations.json",
        "themes.json",
        "stages.json",
        "chats.json",
        "wardrobe.json",
        "inspiration.json",
        "progression.json",
        "tasks.json",
        "staff.json",
        "guide.json",
        "mechanics.json",
    )
    optional = ("map.json",)
    documents: dict[str, dict[str, Any]] = {}
    for name in required:
        metadata = files.get(name)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("sha256"), str):
            raise AnonTokyoPlayerGuideError(f"projection file is not indexed: {name}")
        try:
            data = (projection_root / name).read_bytes()
        except OSError as exc:
            raise AnonTokyoPlayerGuideError(f"projection file is unreadable: {name}") from exc
        if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            raise AnonTokyoPlayerGuideError(f"projection file hash mismatch: {name}")
        try:
            document = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AnonTokyoPlayerGuideError(f"projection file is invalid: {name}") from exc
        if not isinstance(document, dict):
            raise AnonTokyoPlayerGuideError(f"projection file must be an object: {name}")
        documents[name] = document
    for name in optional:
        if name not in files:
            continue
        metadata = files.get(name)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("sha256"), str):
            raise AnonTokyoPlayerGuideError(f"projection file is not indexed: {name}")
        try:
            data = (projection_root / name).read_bytes()
        except OSError as exc:
            raise AnonTokyoPlayerGuideError(f"projection file is unreadable: {name}") from exc
        if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            raise AnonTokyoPlayerGuideError(f"projection file hash mismatch: {name}")
        try:
            document = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AnonTokyoPlayerGuideError(f"projection file is invalid: {name}") from exc
        if not isinstance(document, dict):
            raise AnonTokyoPlayerGuideError(f"projection file must be an object: {name}")
        documents[name] = document
    return manifest, documents


def _public_id(kind: str, source_id: Any) -> str:
    digest = hashlib.sha256(f"{kind}:{source_id}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


def _player_text(value: Any, *, fallback: str | None = None) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate and not RAW_TEXT_KEY.fullmatch(candidate):
            return candidate
        return fallback
    if not isinstance(value, dict):
        return fallback
    values = value.get("values")
    statuses = value.get("status")
    if not isinstance(values, dict):
        return fallback
    for locale in ("zh-CN", "zh-TW", "en", "ja"):
        candidate = values.get(locale)
        status = statuses.get(locale) if isinstance(statuses, dict) else "verified"
        if (
            status == "verified"
            and isinstance(candidate, str)
            and candidate.strip()
            and not RAW_TEXT_KEY.fullmatch(candidate.strip())
        ):
            return candidate.strip()
    return fallback


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _format_duration(seconds: Any) -> str | None:
    value = _as_number(seconds)
    if value is None or value < 0:
        return None
    whole = int(value)
    if whole % 3600 == 0 and whole:
        return f"{whole // 3600} 小时"
    if whole % 60 == 0 and whole:
        return f"{whole // 60} 分钟"
    return f"{whole} 秒"


def _format_size(value: Any) -> str | None:
    if isinstance(value, list) and len(value) == 2:
        parts = [_as_number(part) for part in value]
        if all(isinstance(part, (int, float)) for part in parts):
            return f"{parts[0]:g} × {parts[1]:g}"
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return f"{parts[0]} × {parts[1]}"
    return None


def _format_delivery_effect(template: str, rendered_value: str) -> str:
    return " ".join(template.replace("{0}", rendered_value).split())


def _player_effect_name(value: Any) -> str | None:
    name = _player_text(value)
    if not name:
        return None
    if "<" not in name and "{" not in name:
        return name
    labels = (
        ("顾客上限", "顾客上限提升"),
        ("刷新频率", "顾客刷新频率"),
        ("灵感", "灵感值提升"),
        ("经验", "额外经验值"),
        ("银币", "额外银币"),
    )
    return next((label for marker, label in labels if marker in name), "FEVER 效果")


def _project_goods(
    document: Mapping[str, Any], *, formulas_verified: bool
) -> tuple[
    dict[str, Any],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    int,
]:
    category_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="未分类") or "未分类"
        for item in document.get("categories", [])
        if isinstance(item, dict)
    }
    tag_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="未命名标签")
        or "未命名标签"
        for item in document.get("tags", [])
        if isinstance(item, dict)
    }
    records: list[dict[str, Any]] = []
    name_by_source: dict[str, str] = {}
    public_by_source: dict[str, str] = {}
    hidden_goods = 0
    for item in document.get("records", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id"))
        name = _player_text(item.get("name"), fallback="名称暂未确认") or "名称暂未确认"
        name_by_source[source_id] = name
        if not item.get("visible", True):
            hidden_goods += 1
            continue
        public_id = _public_id("goods", source_id)
        public_by_source[source_id] = public_id
        purchase = item.get("purchase") if isinstance(item.get("purchase"), dict) else {}
        sale_values = item.get("saleCoinCounts")
        sale = sale_values[0] if isinstance(sale_values, list) and sale_values else None
        record: dict[str, Any] = {
            "id": public_id,
            "name": name,
            "category": category_names.get(str(item.get("categoryId")), "未分类"),
            "tags": [
                tag_names[tag]
                for tag in (str(value) for value in item.get("tagIds", []))
                if tag in tag_names
            ],
            "imageKey": item.get("mediaKey") or None,
            "purchaseQuantity": _as_number(purchase.get("itemCount")),
            "purchaseCost": _as_number(purchase.get("cost")),
            "saleCoins": _as_number(sale),
            "deliverySeconds": _as_number(item.get("deliveryDuration")),
            "deliveryTime": _format_duration(item.get("deliveryDuration")),
            "unlockConditions": [],
        }
        unlock = item.get("unlock") if isinstance(item.get("unlock"), dict) else {}
        unlock_count = _as_number(unlock.get("count"))
        unlock_cost = _as_number(unlock.get("costCount"))
        if unlock_count not in (None, 0):
            record["unlockConditions"].append(f"解锁进度达到 {unlock_count:g}" if isinstance(unlock_count, float) else f"解锁进度达到 {unlock_count}")
        if unlock_cost not in (None, 0):
            record["unlockConditions"].append(f"解锁费用 {unlock_cost:g}" if isinstance(unlock_cost, float) else f"解锁费用 {unlock_cost}")
        if formulas_verified:
            cost = record["purchaseCost"]
            price = record["saleCoins"]
            quantity = record["purchaseQuantity"]
            duration = record["deliverySeconds"]
            if all(isinstance(value, (int, float)) for value in (cost, price, quantity, duration)) and duration > 0:
                profit = price - cost
                record["profitPerUnit"] = profit
                record["profitPerHour"] = profit * quantity * 3600 / duration
        records.append(record)
    records.sort(key=lambda item: (item["category"], item["name"], item["id"]))
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "records": records,
            "categories": sorted({item["category"] for item in records}),
            "tags": sorted({tag for item in records for tag in item["tags"]}),
        },
        name_by_source,
        public_by_source,
        tag_names,
        category_names,
        hidden_goods,
    )


def _store_sort_key(item: Mapping[str, Any]) -> tuple[float, str]:
    number = _as_number(item.get("id"))
    return (float(number) if number is not None else float("inf"), str(item.get("id")))


def _project_store(
    document: Mapping[str, Any], *, currency_names: Mapping[str, str]
) -> dict[str, Any]:
    source_levels = [
        item
        for item in document.get("storeLevels", [])
        if isinstance(item, dict)
    ]
    source_levels.sort(key=_store_sort_key)
    deliveries_by_level: dict[int, list[str]] = {}
    for delivery in document.get("deliveries", []):
        if not isinstance(delivery, dict):
            continue
        fields = delivery.get("fields") if isinstance(delivery.get("fields"), dict) else {}
        unlock_level = _as_number(fields.get("unlockShopLevel"))
        name = _player_text(delivery.get("name"))
        if isinstance(unlock_level, (int, float)) and name:
            deliveries_by_level.setdefault(int(unlock_level), []).append(name)
    public_ids = {
        str(item.get("id")): _public_id("store", item.get("id"))
        for item in source_levels
    }
    levels: list[dict[str, Any]] = []
    for index, item in enumerate(source_levels):
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        level = index + 1
        requirements = []
        for label, key, unit in (
            ("升级费用", "buyItemCount", "货币"),
            ("店铺人气要求", "shopPopularityRequirement", "人气"),
            ("玩家等级要求", "level", "级"),
        ):
            value = _as_number(fields.get(key))
            if value not in (None, 0):
                requirements.append({"label": label, "value": value, "unit": unit})
        stats = []
        size = _format_size(fields.get("size") or fields.get("roomSize"))
        if size:
            stats.append({"label": "店铺面积", "value": size})
        for label, key in (("顾客上限", "customerCount"), ("店铺人气", "popularityCount")):
            value = _as_number(fields.get(key))
            if value is not None:
                stats.append({"label": label, "value": value})
        next_item = source_levels[index + 1] if index + 1 < len(source_levels) else None
        levels.append(
            {
                "id": public_ids[str(item.get("id"))],
                "level": level,
                "name": f"店铺等级 {level}",
                "upgradeRequirements": requirements,
                "stats": stats,
                "unlocks": sorted(deliveries_by_level.get(level, [])),
                "nextLevelId": public_ids.get(str(next_item.get("id"))) if next_item else None,
            }
        )
    delivery_skills = {
        str(item.get("id")): item
        for item in document.get("deliverySkills", [])
        if isinstance(item, dict)
    }
    delivery_options = []
    deliveries = [
        item for item in document.get("deliveries", []) if isinstance(item, dict)
    ]
    deliveries.sort(key=_store_sort_key)
    for item in deliveries:
        fields = _progression_fields(item)
        effect = None
        reward = fields.get("deliverySkillReward")
        if isinstance(reward, str) and reward.strip():
            parts = [part.strip() for part in reward.split(",")]
            if len(parts) == 2:
                definition = delivery_skills.get(parts[0])
                template = _player_text(definition.get("name")) if definition else None
                value = _as_number(parts[1])
                if template and value is not None:
                    rendered = f"{value:g}" if isinstance(value, float) else str(value)
                    effect = _format_delivery_effect(template, rendered)
        cost_count = _as_number(fields.get("unlockCostCount"))
        cost_type = str(fields.get("unlockCostType"))
        delivery_options.append(
            {
                "id": _public_id("delivery", item.get("id")),
                "name": _player_text(item.get("name"), fallback="配送员") or "配送员",
                "unlockShopLevel": _as_number(fields.get("unlockShopLevel")),
                "unlockCost": (
                    {
                        "name": currency_names.get(cost_type, "未命名货币"),
                        "count": cost_count,
                    }
                    if cost_count not in (None, 0)
                    else None
                ),
                "effect": effect,
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "levels": levels,
        "deliveryOptions": delivery_options,
    }


def _progression_fields(item: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = item.get("fields")
    return fields if isinstance(fields, dict) else {}


def _project_growth(
    document: Mapping[str, Any], *, currency_names: Mapping[str, str]
) -> dict[str, Any]:
    source_levels = [
        item for item in document.get("playerLevels", []) if isinstance(item, dict)
    ]
    source_levels.sort(
        key=lambda item: (
            _as_number(_progression_fields(item).get("level")) or 0,
            str(item.get("id")),
        )
    )
    levels = []
    for index, item in enumerate(source_levels):
        fields = _progression_fields(item)
        level = _as_number(fields.get("level"))
        required_exp = _as_number(fields.get("exp"))
        next_fields = (
            _progression_fields(source_levels[index + 1])
            if index + 1 < len(source_levels)
            else {}
        )
        next_exp = _as_number(next_fields.get("exp"))
        exp_to_next = (
            next_exp - required_exp
            if isinstance(next_exp, (int, float))
            and isinstance(required_exp, (int, float))
            else None
        )
        weights = [
            _as_number(fields.get(f"spawnRateLevel{tier}")) for tier in range(1, 9)
        ]
        active_tiers = [
            tier
            for tier, weight in enumerate(weights, start=1)
            if isinstance(weight, (int, float)) and weight > 0
        ]
        levels.append(
            {
                "id": _public_id("growth", item.get("id")),
                "level": level,
                "requiredExp": required_exp,
                "expToNext": exp_to_next,
                "staminaLimit": _as_number(fields.get("strengthLimit")),
                "customerLimit": _as_number(fields.get("customerCount")),
                "customerTiers": active_tiers,
            }
        )

    def capacity_steps(key: str, kind: str) -> list[dict[str, Any]]:
        source = [
            item for item in document.get(key, []) if isinstance(item, dict)
        ]
        source.sort(key=_store_sort_key)
        result = []
        for index, item in enumerate(source, start=1):
            fields = _progression_fields(item)
            cost_count = _as_number(fields.get("buyItemCount"))
            currency = currency_names.get(str(fields.get("buyItemId")))
            cost = None
            if cost_count not in (None, 0):
                cost = {
                    "name": currency or "未命名货币",
                    "count": cost_count,
                }
            result.append(
                {
                    "id": _public_id(kind, item.get("id")),
                    "step": index,
                    "capacity": _as_number(fields.get("limitCount")),
                    "cost": cost,
                }
            )
        return result

    return {
        "schemaVersion": SCHEMA_VERSION,
        "records": levels,
        "warehouseSteps": capacity_steps("warehouses", "warehouse"),
        "safeDepositSteps": capacity_steps("safeDepositBoxes", "safe-deposit"),
    }


def _project_customers(
    document: Mapping[str, Any],
    *,
    staff_by_identity: Mapping[str, Mapping[str, Any]],
    staff_source_by_identity: Mapping[str, str],
    band_by_character: Mapping[str, str],
    tag_names: Mapping[str, str],
    goods: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    records = []
    hidden = 0
    for item in document.get("characterCustomers", []):
        if not isinstance(item, dict):
            hidden += 1
            continue
        fields = _progression_fields(item)
        identity = str(fields.get("bangIdentityNumber"))
        staff = staff_by_identity.get(identity)
        source_character = staff_source_by_identity.get(identity)
        preferences = [
            tag_names[tag]
            for tag in (
                str(fields.get("likeTag1")),
                str(fields.get("likeTag2")),
            )
            if tag in tag_names
        ]
        if not staff or len(preferences) != 2:
            hidden += 1
            continue
        matching_goods = []
        for goods_item in goods.get("records", []):
            if not isinstance(goods_item, dict):
                continue
            matched = [tag for tag in preferences if tag in goods_item.get("tags", [])]
            if not matched:
                continue
            matching_goods.append(
                {
                    "id": goods_item["id"],
                    "name": goods_item["name"],
                    "category": goods_item["category"],
                    "imageKey": goods_item.get("imageKey"),
                    "matchedTags": matched,
                }
            )
        matching_goods.sort(
            key=lambda value: (-len(value["matchedTags"]), value["category"], value["name"])
        )
        records.append(
            {
                "id": _public_id("customer", item.get("id")),
                "character": {
                    "id": staff["id"],
                    "name": staff["name"],
                    "imageKey": staff.get("imageKey"),
                },
                "band": band_by_character.get(source_character or "", ""),
                "preferences": preferences,
                "matchingGoods": matching_goods,
            }
        )
    records.sort(key=lambda value: (value["band"], value["character"]["name"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "records": records,
        "bands": sorted({value["band"] for value in records if value["band"]}),
        "tags": sorted({tag for value in records for tag in value["preferences"]}),
    }, hidden


def _wardrobe_series(name: str, type_name: str) -> str:
    match = re.fullmatch(r"(.+?)\[([^\]]+)\]", name)
    if not match:
        return "其他"
    base, detail = (part.strip() for part in match.groups())
    detail_without_type = detail
    for marker in (type_name, "服装"):
        detail_without_type = detail_without_type.replace(marker, "")
    detail_without_type = detail_without_type.strip(" ·-")
    return detail_without_type or base or "其他"


def _project_wardrobe(
    document: Mapping[str, Any],
    *,
    goods_names: Mapping[str, str],
    goods_public_ids: Mapping[str, str],
    goods_by_public_id: Mapping[str, Mapping[str, Any]],
    staff_by_source: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], int]:
    type_names = {1: "头饰", 2: "上衣", 3: "下装", 4: "鞋袜", 5: "套装"}
    records = []
    hidden = 0
    unconfirmed = 0
    for item in document.get("records", []):
        if not isinstance(item, dict) or item.get("visible") is not True:
            hidden += 1
            continue
        type_id = _as_number(item.get("type"))
        type_name = type_names.get(type_id)
        name = _player_text(item.get("name"))
        image_key = item.get("iconKey")
        if not type_name or not name or not isinstance(image_key, str) or not image_key:
            hidden += 1
            continue
        attribution_verified = bool(item.get("characterAttributionVerified"))
        attribution_status = str(item.get("characterAttributionStatus") or "unresolved")
        if not attribution_verified:
            unconfirmed += 1
        characters = []
        for source_id in item.get("characterIds", []) or []:
            staff = staff_by_source.get(str(source_id))
            if staff:
                characters.append(
                    {
                        "id": staff["id"],
                        "name": staff["name"],
                    }
                )
        associated_goods = []
        for source_id in item.get("goodsIds", []):
            public_id = goods_public_ids.get(str(source_id))
            goods_item = goods_by_public_id.get(public_id or "")
            if public_id and goods_item:
                associated_goods.append(
                    {
                        "id": public_id,
                        "name": goods_names.get(str(source_id), goods_item["name"]),
                        "imageKey": goods_item.get("imageKey"),
                    }
                )
        associated_goods.sort(key=lambda value: value["name"])
        characters.sort(key=lambda value: value["name"])
        records.append(
            {
                "id": _public_id("wardrobe", item.get("id")),
                "name": name,
                "series": _wardrobe_series(name, type_name),
                "type": type_name,
                "imageKey": image_key,
                "rarity": _as_number(item.get("rarity")),
                "popularity": _as_number(item.get("popularity")),
                "characters": characters,
                "associatedGoods": associated_goods,
                "attributionStatus": attribution_status,
                "attributionVerified": attribution_verified,
            }
        )
    records.sort(key=lambda value: (value["series"], value["type"], value["name"]))
    series_list = sorted({value["series"] for value in records})
    type_list = [name for _, name in sorted(type_names.items())]
    character_names = sorted(
        {character["name"] for value in records for character in value["characters"]}
    )
    by_character: dict[str, list[dict[str, Any]]] = {}
    for value in records:
        for character in value["characters"]:
            by_character.setdefault(character["name"], []).append(value)
    character_outfits: list[dict[str, Any]] = []
    for char_name, items in sorted(by_character.items()):
        by_type: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_type.setdefault(item["type"], []).append(item)
        outfit: list[dict[str, Any]] = []
        for type_name in type_list:
            pieces = by_type.get(type_name, [])
            if pieces:
                outfit.append({"type": type_name, "pieces": pieces})
        if outfit:
            character_outfits.append(
                {
                    "character": char_name,
                    "pieceCount": sum(len(part["pieces"]) for part in outfit),
                    "outfit": outfit,
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "records": records,
        "types": type_list,
        "series": series_list,
        "characters": character_names,
        "characterOutfits": character_outfits,
        "unconfirmedAttributionCount": unconfirmed,
    }, hidden


def _project_inspiration(document: Mapping[str, Any]) -> dict[str, Any]:
    source = [item for item in document.get("records", []) if isinstance(item, dict)]
    source.sort(
        key=lambda item: _as_number(
            item.get("range", {}).get("minimum")
            if isinstance(item.get("range"), dict)
            else None
        )
        or 0
    )
    records = []
    for index, item in enumerate(source):
        tier_range = item.get("range") if isinstance(item.get("range"), dict) else {}
        next_range = (
            source[index + 1].get("range")
            if index + 1 < len(source)
            and isinstance(source[index + 1].get("range"), dict)
            else {}
        )
        records.append(
            {
                "id": _public_id("inspiration", item.get("id")),
                "minimum": _as_number(tier_range.get("minimum")),
                "maximum": _as_number(tier_range.get("maximum")),
                "purchaseCount": _as_number(item.get("purchaseCount")),
                "extraPurchaseChance": _as_number(item.get("extraPurchaseChance")),
                "nextMinimum": _as_number(next_range.get("minimum")),
            }
        )
    return {"schemaVersion": SCHEMA_VERSION, "records": records}


def _replace_placeholders(template: str, values: Sequence[str]) -> str:
    result = template
    replaced = False
    for index, value in enumerate(values):
        token = "{" + str(index) + "}"
        if token in result:
            result = result.replace(token, value)
            replaced = True
    if replaced:
        return result
    suffix = " · ".join(value for value in values if value)
    return f"{template}：{suffix}" if suffix else template


def _task_parameter_text(
    name: Any,
    value: Any,
    *,
    goods_names: Mapping[str, str],
    tag_names: Mapping[str, str],
    category_names: Mapping[str, str],
    decoration_names: Mapping[str, str],
    decoration_type_names: Mapping[str, str],
    staff_names: Mapping[str, str],
    clerk_names: Mapping[str, str],
    suit_names: Mapping[str, str],
) -> str | None:
    key = str(name or "").casefold()
    source = str(value)
    if "goods" in key and source in goods_names:
        return goods_names[source]
    if "tag" in key and source in tag_names:
        return tag_names[source]
    if "goodstype" in key and source in category_names:
        return category_names[source]
    if key == "decorationid" and source in decoration_names:
        return decoration_names[source]
    if key == "subtypeid" and source in decoration_type_names:
        return decoration_type_names[source]
    if key == "characterid" and source in staff_names:
        return staff_names[source]
    if key == "clerkid" and source in clerk_names:
        return clerk_names[source]
    if key == "suitid" and source in suit_names:
        return suit_names[source]
    if key in {
        "goodsid",
        "goodstypeid",
        "tagid",
        "decorationid",
        "subtypeid",
        "characterid",
        "clerkid",
        "suitid",
    }:
        return None
    number = _as_number(value)
    if number is not None:
        return f"{number:g}" if isinstance(number, float) else f"{number}"
    if isinstance(value, str) and value.strip() and not RAW_TEXT_KEY.fullmatch(value.strip()):
        return value.strip()
    return None


def _project_tasks(
    document: Mapping[str, Any],
    *,
    goods_names: Mapping[str, str],
    tag_names: Mapping[str, str],
    category_names: Mapping[str, str],
    decoration_names: Mapping[str, str],
    decoration_type_names: Mapping[str, str],
    staff_names: Mapping[str, str],
    clerk_names: Mapping[str, str],
    suit_names: Mapping[str, str],
) -> tuple[dict[str, Any], int]:
    task_types = {
        str(item.get("id")): item
        for item in document.get("taskTypes", [])
        if isinstance(item, dict)
    }
    tab_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="任务") or "任务"
        for item in document.get("tabs", [])
        if isinstance(item, dict)
    }
    reward_items = {
        f"{item.get('rewardType')}:{item.get('id')}": item
        for item in document.get("rewardItems", [])
        if isinstance(item, dict)
    }
    source_records = [item for item in document.get("records", []) if isinstance(item, dict)]
    public_ids = {
        str(item.get("id")): _public_id("task", item.get("id"))
        for item in source_records
    }
    records: list[dict[str, Any]] = []
    reward_names: dict[str, str] = {}
    hidden = 0
    for item in source_records:
        definition = task_types.get(str(item.get("taskTypeId")))
        template = _player_text(definition.get("description")) if definition else None
        if not template:
            hidden += 1
            continue
        values = []
        complete = True
        for parameter in item.get("parameters", []):
            if not isinstance(parameter, dict):
                complete = False
                break
            rendered = _task_parameter_text(
                parameter.get("name"),
                parameter.get("value"),
                goods_names=goods_names,
                tag_names=tag_names,
                category_names=category_names,
                decoration_names=decoration_names,
                decoration_type_names=decoration_type_names,
                staff_names=staff_names,
                clerk_names=clerk_names,
                suit_names=suit_names,
            )
            if rendered is None:
                complete = False
                break
            values.append(rendered)
        if not complete:
            hidden += 1
            continue
        rewards = []
        for reward in item.get("reward", []):
            if not isinstance(reward, dict):
                continue
            kind = str(reward.get("type") or "reward")
            source_item = str(reward.get("itemId") or "item")
            key = _public_id("reward", f"{kind}:{source_item}")
            reward_definition = reward_items.get(f"{kind}:{source_item}")
            reward_icon = reward_definition.get("iconKey") if reward_definition else None
            name = (
                _player_text(reward_definition.get("name"))
                if reward_definition
                else None
            )
            if (
                not name
                and kind == "1"
                and source_item == "4"
                and reward_icon == "AT_Common_Icon_Experience"
            ):
                name = "经验"
            name = name or goods_names.get(source_item, "奖励物品")
            reward_names[key] = name
            rewards.append(
                {
                    "key": key,
                    "name": name,
                    "count": _as_number(reward.get("count")),
                    "imageKey": reward_icon,
                }
            )
        source_id = str(item.get("id"))
        records.append(
            {
                "id": public_ids[source_id],
                "category": tab_names.get(str(item.get("taskTabId")), "任务"),
                "condition": _replace_placeholders(template, values),
                "rewards": rewards,
                "previousTaskId": public_ids.get(str(item.get("predecessorTaskId"))),
            }
        )
    reward_index: dict[str, list[str]] = {}
    for record in records:
        for reward in record["rewards"]:
            reward_index.setdefault(reward["key"], []).append(record["id"])
    rewards = [
        {"key": key, "name": reward_names[key], "taskIds": sorted(task_ids)}
        for key, task_ids in sorted(reward_index.items(), key=lambda pair: reward_names[pair[0]])
    ]
    records.sort(key=lambda item: (item["category"], item["condition"], item["id"]))
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "records": records,
            "categories": sorted({item["category"] for item in records}),
            "rewards": rewards,
        },
        hidden,
    )


def _ability_effect(definition: Mapping[str, Any], value: Any) -> str:
    template = _player_text(definition.get("value"))
    number = _as_number(value)
    rendered = str(number if number is not None else value)
    if template:
        return template.replace("{0}", rendered)
    return rendered


def _project_staff(document: Mapping[str, Any]) -> dict[str, Any]:
    abilities = {
        str(item.get("id")): item
        for item in document.get("passiveAbilities", [])
        if isinstance(item, dict)
    }
    roles = {
        str(item.get("id")): item
        for item in document.get("roles", [])
        if isinstance(item, dict)
    }
    records = []
    for item in document.get("records", []):
        if not isinstance(item, dict):
            continue
        projected_abilities = []
        for ability in item.get("passiveAbilities", []):
            if not isinstance(ability, dict):
                continue
            identity = str(ability.get("abilityId"))
            definition = abilities.get(identity)
            if not definition:
                continue
            ability_name = _player_text(definition.get("name"), fallback="能力") or "能力"
            client_semantics_verified = bool(item.get("clientSemanticsVerified"))
            projected: dict[str, Any] = {
                "name": ability_name,
                "imageKey": definition.get("iconKey") or None,
                "effectVerified": client_semantics_verified,
                "effectPlaceholder": not client_semantics_verified,
            }
            projected["effect"] = _ability_effect(definition, ability.get("value"))
            role = roles.get(identity)
            role_name = _player_text(role.get("name")) if role else None
            if role_name:
                projected["roleInclination"] = {
                    "name": role_name,
                    "imageKey": role.get("iconKey") or None,
                    "value": _as_number(ability.get("value")),
                }
            projected_abilities.append(projected)
        unlock = item.get("unlock") if isinstance(item.get("unlock"), dict) else {}
        unlock_cost = _as_number(unlock.get("itemCount"))
        records.append(
            {
                "id": _public_id("staff", item.get("id")),
                "name": _player_text(item.get("name"), fallback="名称暂未确认")
                or "名称暂未确认",
                "imageKey": item.get("imageKey") or None,
                "levelLimit": _as_number(item.get("levelLimit")),
                "unlock": f"解锁费用 {unlock_cost}" if unlock_cost not in (None, 0) else None,
                "abilities": projected_abilities,
                "statsVerified": bool(item.get("clientSemanticsVerified")),
                "statsNote": (
                    None
                    if item.get("clientSemanticsVerified")
                    else "被动能力来自原始数值串，客户端语义未闭环，页面不展示具体效果"
                ),
            }
        )
    records.sort(key=lambda item: (item["name"], item["id"]))
    assignment = (
        document.get("assignmentStudio")
        if isinstance(document.get("assignmentStudio"), dict)
        else None
    )
    assignment_studio = None
    if assignment is not None:
        role_labels = {
            "cashier": "收银员",
            "sales": "导购员",
            "restock": "补货员",
        }
        projected_roles = []
        for assignment_role in assignment.get("roles", []):
            if not isinstance(assignment_role, dict):
                continue
            role_id = str(assignment_role.get("id") or "")
            source_role = roles.get(str(assignment_role.get("sourceId")))
            if role_id not in role_labels or not source_role:
                continue
            projected_roles.append(
                {
                    "id": role_id,
                    "name": role_labels[role_id],
                    "imageKey": source_role.get("iconKey") or None,
                }
            )
        capacity_by_level = assignment.get("capacityByLevel")
        free_capacities = assignment.get("freePreviewCapacities")
        if (
            len(projected_roles) == 3
            and isinstance(capacity_by_level, list)
            and len(capacity_by_level) == 20
            and isinstance(free_capacities, dict)
        ):
            assignment_studio = {
                "schemaVersion": SCHEMA_VERSION,
                "roles": projected_roles,
                "capacityByLevel": capacity_by_level,
                "freePreviewCapacities": free_capacities,
                "cashierCapacityRule": assignment.get("cashierCapacityRule"),
            }
    result = {"schemaVersion": SCHEMA_VERSION, "records": records}
    if assignment_studio is not None:
        result["assignmentStudio"] = assignment_studio
    return result


def _project_furniture(
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], int, dict[str, dict[str, Any]]]:
    main_types = {
        str(item.get("id")): name
        for item in document.get("mainTypes", [])
        if isinstance(item, dict)
        and item.get("visible") is True
        and (name := _player_text(item.get("name")))
    }
    sub_types = {
        str(item.get("id")): name
        for item in document.get("subTypes", [])
        if isinstance(item, dict)
        and item.get("visible") is True
        and (name := _player_text(item.get("name")))
    }
    records = []
    records_by_source: dict[str, dict[str, Any]] = {}
    hidden = 0
    for item in document.get("records", []):
        if not isinstance(item, dict):
            hidden += 1
            continue
        name = _player_text(item.get("name"))
        category = main_types.get(str(item.get("typeId")))
        source_id = str(item.get("id"))
        is_stage = source_id in {"11001", "11002"}
        sub_category = sub_types.get(str(item.get("subTypeId")))
        if is_stage and not sub_category:
            sub_category = "舞台"
        size = _format_size(item.get("size"))
        condition = item.get("condition")
        condition_type = condition.get("type") if isinstance(condition, dict) else None
        condition_value = (
            _as_number(condition.get("value")) if isinstance(condition, dict) else None
        )
        if condition_type in (None, 0):
            unlock = None
        elif condition_type == 1 and condition_value is not None:
            unlock = f"店铺等级 {condition_value:g}"
        else:
            hidden += 1
            continue
        if not all((name, category, sub_category, size)):
            hidden += 1
            continue
        purchase = item.get("purchase") if isinstance(item.get("purchase"), dict) else {}
        sale = item.get("sale") if isinstance(item.get("sale"), dict) else {}
        record = {
                "id": _public_id("furniture", item.get("id")),
                "name": name,
                "category": category,
                "subCategory": sub_category,
                "imageKey": item.get("mediaKey") or None,
                **(
                    {"sceneImageKey": item.get("sceneMediaKey")}
                    if item.get("sceneMediaKey")
                    else {}
                ),
                "size": size,
                "purchase": _as_number(purchase.get("itemCount")),
                "sale": _as_number(sale.get("itemCount")),
                "limit": _as_number(item.get("limit")),
                "unlock": unlock,
            }
        records.append(record)
        records_by_source[source_id] = record
    records.sort(
        key=lambda item: (
            item["category"],
            item["subCategory"],
            item["name"],
            item["id"],
        )
    )
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "records": records,
            "categories": sorted({item["category"] for item in records}),
            "subCategories": sorted({item["subCategory"] for item in records}),
        },
        hidden,
        records_by_source,
    )


def _dimension_pair(value: Any) -> dict[str, int] | None:
    if isinstance(value, list) and len(value) == 2:
        parts = [_as_number(part) for part in value]
    elif isinstance(value, str):
        separator = "×" if "×" in value else ","
        parts = [_as_number(part.strip()) for part in value.split(separator)]
    else:
        return None
    if len(parts) != 2 or not all(isinstance(part, int) and part > 0 for part in parts):
        return None
    return {"width": parts[0], "height": parts[1]}


def _direction_list(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    result = sorted(
        {
            number
            for item in values
            if isinstance((number := _as_number(item)), int) and 0 <= number <= 3
        }
    )
    return result


def _project_studio(
    map_document: Mapping[str, Any],
    decoration_document: Mapping[str, Any],
    *,
    furniture_by_source: Mapping[str, Mapping[str, Any]],
    store: Mapping[str, Any],
    catalog_hash: str | None,
) -> dict[str, Any]:
    furniture = []
    for item in decoration_document.get("records", []):
        if not isinstance(item, dict):
            continue
        player = furniture_by_source.get(str(item.get("id")))
        footprint = _dimension_pair(item.get("size"))
        directions = _direction_list(item.get("direction"))
        if not player or not footprint or not directions or not player.get("imageKey"):
            continue
        furniture.append(
            {
                "id": player["id"],
                "name": player["name"],
                "category": player["category"],
                "subCategory": player["subCategory"],
                "imageKey": player.get("sceneImageKey") or player["imageKey"],
                "catalogImageKey": player["imageKey"],
                "unlock": player.get("unlock"),
                "footprint": footprint,
                "directions": directions,
            }
        )
    furniture.sort(key=lambda item: (item["category"], item["subCategory"], item["name"]))
    studio_furniture_by_id = {item["id"]: item for item in furniture}

    store_sizes = []
    for level in store.get("levels", []):
        if not isinstance(level, dict):
            continue
        size = next(
            (
                _dimension_pair(stat.get("value"))
                for stat in level.get("stats", [])
                if isinstance(stat, dict) and stat.get("label") == "店铺面积"
            ),
            None,
        )
        if size:
            store_sizes.append({"level": level.get("level"), **size})

    source_map = map_document.get("map")
    if not isinstance(source_map, dict):
        raise AnonTokyoPlayerGuideError("map projection has no map document")
    grid = source_map.get("grid")
    grid_width = grid.get("width") if isinstance(grid, dict) else None
    anchor = source_map.get("marketTileIndex")
    if not isinstance(grid_width, int) or grid_width <= 0 or not isinstance(anchor, int):
        raise AnonTokyoPlayerGuideError("map projection has no valid store anchor")
    anchor_x = anchor % grid_width
    anchor_y = anchor // grid_width

    def local_position(tile_index: Any) -> dict[str, int] | None:
        if not isinstance(tile_index, int):
            return None
        return {
            "x": tile_index % grid_width - anchor_x,
            "y": anchor_y - tile_index // grid_width,
        }

    initial_layout = []
    for item in source_map.get("initialObjects", []):
        if not isinstance(item, dict):
            continue
        player = furniture_by_source.get(str(item.get("configId")))
        if not player:
            continue
        tile_index = item.get("tileIndex")
        if not isinstance(tile_index, int):
            continue
        direction = item.get("direction")
        position = local_position(tile_index)
        if position is None:
            continue
        x = position["x"]
        y = position["y"]
        studio_furniture = studio_furniture_by_id.get(player["id"])
        if studio_furniture and direction == 3:
            # MapConfig anchors direction-3 wall pieces on the tile immediately
            # left of their occupied rectangle. Studio stores top-left rectangles.
            x += studio_furniture["footprint"]["height"] - 1
        initial_layout.append(
            {
                "instanceId": _public_id("layout-instance", item.get("instanceId")),
                "furnitureId": player["id"],
                "x": x,
                "y": y,
                "direction": direction,
            }
        )
    initial_layout.sort(key=lambda item: item["instanceId"])

    maximum_store = max(
        store_sizes,
        key=lambda size: size["width"] * size["height"],
        default={"width": 0, "height": 0},
    )

    def outside_maximum_store(tile_index: int) -> bool:
        position = local_position(tile_index)
        if position is None:
            return True
        x = position["x"]
        y = position["y"]
        return not (
            0 <= x < maximum_store["width"]
            and 0 <= y < maximum_store["height"]
        )

    decorations_by_source = {
        str(item.get("id")): item
        for item in decoration_document.get("records", [])
        if isinstance(item, dict)
    }
    warehouse_source = source_map.get("warehouse")
    warehouse_tile = (
        warehouse_source.get("tileIndex")
        if isinstance(warehouse_source, dict)
        else None
    )
    warehouse_position = local_position(warehouse_tile)
    if warehouse_position is None:
        raise AnonTokyoPlayerGuideError("map projection has no valid warehouse anchor")
    warehouse_definition = decorations_by_source.get(
        str(warehouse_source.get("configId"))
        if isinstance(warehouse_source, dict)
        else ""
    )
    warehouse_footprint = _dimension_pair(
        warehouse_definition.get("size")
        if isinstance(warehouse_definition, dict)
        else None
    ) or {"width": 3, "height": 3}
    warehouse_image_key = (
        warehouse_definition.get("sceneMediaKey")
        if isinstance(warehouse_definition, dict)
        else None
    ) or "AT_Map_Outdoor_Warehouse_Full"

    delivery_position = local_position(source_map.get("deliveryStartTileIndex"))
    if delivery_position is None:
        raise AnonTokyoPlayerGuideError("map projection has no valid delivery anchor")

    max_width = int(maximum_store.get("width") or 0)
    max_height = int(maximum_store.get("height") or 0)
    core_min_x = min(0, warehouse_position["x"], delivery_position["x"])
    core_min_y = min(0, warehouse_position["y"], delivery_position["y"])
    core_max_x = max(
        max_width - 1,
        warehouse_position["x"] + warehouse_footprint["width"] - 1,
        delivery_position["x"],
    )
    core_max_y = max(
        max_height - 1,
        warehouse_position["y"] + warehouse_footprint["height"] - 1,
        delivery_position["y"],
    )
    scene_bounds = {
        "minX": core_min_x - 4,
        "minY": core_min_y - 4,
        "maxX": core_max_x + 4,
        "maxY": core_max_y + 4,
    }

    static_definitions = {
        str(item.get("configId")): item
        for item in source_map.get("staticDefinitions", [])
        if isinstance(item, dict)
    }
    static_candidates = []
    image_counts: dict[str, int] = {}
    missing_counts: dict[str, int] = {}
    for item in source_map.get("fixedObjects", []):
        if not isinstance(item, dict):
            continue
        position = local_position(item.get("tileIndex"))
        if position is None or not (
            scene_bounds["minX"] <= position["x"] <= scene_bounds["maxX"]
            and scene_bounds["minY"] <= position["y"] <= scene_bounds["maxY"]
        ):
            continue
        definition = static_definitions.get(str(item.get("configId")))
        image_key = definition.get("imageKey") if isinstance(definition, dict) else None
        if isinstance(image_key, str) and image_key:
            image_counts[image_key] = image_counts.get(image_key, 0) + 1
        else:
            missing_key = "unresolved-static-object"
            missing_counts[missing_key] = missing_counts.get(missing_key, 0) + 1
        static_candidates.append((item, position, definition, image_key))

    selected_image_keys = {
        key
        for key, _ in sorted(
            image_counts.items(),
            key=lambda pair: (-pair[1], pair[0]),
        )[:MAX_SCENE_STATIC_IMAGE_KEYS]
    }
    static_objects = []
    omitted_image_counts: dict[str, int] = {}
    for item, position, definition, image_key in static_candidates:
        if image_key not in selected_image_keys:
            if isinstance(image_key, str) and image_key:
                omitted_image_counts[image_key] = omitted_image_counts.get(image_key, 0) + 1
            continue
        footprint = (
            definition.get("footprint")
            if isinstance(definition, dict)
            and isinstance(definition.get("footprint"), dict)
            else {"width": 1, "height": 1}
        )
        static_objects.append(
            {
                "id": _public_id("scene-object", item.get("instanceId")),
                **position,
                "direction": item.get("direction", 0),
                "footprint": footprint,
                "imageKey": image_key,
            }
        )
    static_objects.sort(key=lambda item: (item["x"] + item["y"], item["id"]))

    missing_assets = [
        {
            "id": _public_id("scene-missing", key),
            "kind": "static-environment",
            "reason": "media-budget" if key != "unresolved-static-object" else "unresolved",
            "count": count,
            "critical": False,
        }
        for key, count in sorted({**missing_counts, **omitted_image_counts}.items())
    ]

    delivery_options = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "unlockShopLevel": item.get("unlockShopLevel"),
            "modelStatus": "position-preview",
        }
        for item in store.get("deliveryOptions", [])
        if isinstance(item, dict)
    ]

    return {
        "schemaVersion": STUDIO_SCHEMA_VERSION,
        "catalogHash": catalog_hash,
        "map": {
            "grid": source_map.get("grid"),
            "geometry": source_map.get("geometry"),
            "storeAnchorTileIndex": source_map.get("marketTileIndex"),
            "editableTileIndexes": source_map.get("editableTileIndexes", []),
            "fixedTileIndexes": sorted(
                {
                    item.get("tileIndex")
                    for item in source_map.get("fixedObjects", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("tileIndex"), int)
                    and outside_maximum_store(item["tileIndex"])
                }
            ),
        },
        "storeSizes": store_sizes,
        "furniture": furniture,
        "initialLayout": initial_layout,
        "scene": {
            "projection": {
                "horizontal": "right-down",
                "vertical": "left-down",
                "formula": "x-minus-y__x-plus-y",
            },
            "bounds": scene_bounds,
            "storeAnchor": {"x": 0, "y": 0},
            "warehouse": {
                "id": "warehouse",
                "name": "补货仓库",
                **warehouse_position,
                "direction": 0,
                "footprint": warehouse_footprint,
                "imageKey": warehouse_image_key,
                "fixed": True,
            },
            "deliveryStart": delivery_position,
            "staticObjects": static_objects,
            "missingAssets": missing_assets,
        },
        "deliveryOptions": delivery_options,
        "modes": {
            "gameFaithful": {"defaultLayout": initial_layout},
            "free": {"defaultLayout": []},
        },
    }
def _project_themes(
    document: Mapping[str, Any],
    *,
    furniture_by_source: Mapping[str, Mapping[str, Any]],
    reward_items: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], int]:
    records: list[dict[str, Any]] = []
    unresolved_furniture = 0
    for item in document.get("records", []):
        if not isinstance(item, dict):
            continue
        name = _player_text(item.get("name"))
        if not name:
            continue

        def furniture_links(key: str) -> list[dict[str, Any]]:
            nonlocal unresolved_furniture
            links = []
            for source_id in item.get(key, []):
                furniture = furniture_by_source.get(str(source_id))
                if not furniture:
                    unresolved_furniture += 1
                    continue
                links.append(
                    {
                        "id": furniture["id"],
                        "name": furniture["name"],
                        "imageKey": furniture.get("imageKey"),
                        "size": furniture["size"],
                    }
                )
            return links

        reward = None
        for candidate in item.get("reward", []):
            if not isinstance(candidate, dict):
                continue
            definition = reward_items.get(
                f"{candidate.get('type')}:{candidate.get('itemId')}"
            )
            reward_name = _player_text(definition.get("name")) if definition else None
            if reward_name:
                reward = {
                    "name": reward_name,
                    "count": _as_number(candidate.get("count")),
                    "imageKey": definition.get("iconKey") or None,
                }
                break
        records.append(
            {
                "id": _public_id("theme", item.get("id")),
                "name": name,
                "imageKey": item.get("previewKey") or None,
                "requiredFurniture": furniture_links("requiredDecorationIds"),
                "unlockedFurniture": furniture_links("unlockedDecorationIds"),
                "reward": reward,
            }
        )
    records.sort(key=lambda value: (value["name"], value["id"]))
    return {"schemaVersion": SCHEMA_VERSION, "records": records}, unresolved_furniture


def _project_stages(
    document: Mapping[str, Any],
    *,
    staff_by_source: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], int]:
    records: list[dict[str, Any]] = []
    hidden = 0
    for item in document.get("records", []):
        if not isinstance(item, dict):
            hidden += 1
            continue
        band = _player_text(item.get("bandName"))
        music_source = item.get("music") if isinstance(item.get("music"), dict) else None
        music_name = _player_text(music_source.get("name")) if music_source else None
        duration = _format_duration(music_source.get("duration")) if music_source else None
        members = []
        complete_members = True
        for source_id in item.get("memberIds", []):
            staff = staff_by_source.get(str(source_id))
            if not staff:
                complete_members = False
                break
            members.append(
                {
                    "id": staff["id"],
                    "name": staff["name"],
                    "imageKey": staff.get("imageKey"),
                }
            )
        if not all((band, music_source, music_name, duration, members, complete_members)):
            hidden += 1
            continue
        purchase = (
            music_source.get("purchase")
            if isinstance(music_source.get("purchase"), dict)
            else {}
        )
        if music_source.get("defaultUnlocked") is True:
            unlock = "默认解锁"
        else:
            conditions = []
            level = _as_number(music_source.get("levelLimit"))
            cost = _as_number(purchase.get("itemCount"))
            if level not in (None, 0):
                conditions.append(f"店铺等级 {level:g}")
            if cost not in (None, 0):
                conditions.append(f"解锁费用 {cost:g}")
            unlock = " · ".join(conditions) if conditions else None
        effects = []
        for effect in item.get("feverEffects", []):
            if not isinstance(effect, dict):
                continue
            effect_name = _player_effect_name(effect.get("name"))
            if effect_name:
                effects.append(
                    {"name": effect_name, "imageKey": effect.get("iconKey") or None}
                )
        records.append(
            {
                "id": _public_id("stage", item.get("id")),
                "name": f"{band}舞台",
                "band": band,
                "members": members,
                "music": {
                    "name": music_name,
                    "duration": duration,
                    "imageKey": music_source.get("iconKey") or None,
                    "unlock": unlock,
                },
                "feverEffects": effects,
            }
        )
    effects = []
    for item in document.get("buffs", []):
        if not isinstance(item, dict):
            continue
        name = _player_effect_name(item.get("name"))
        if name:
            effects.append(
                {
                    "name": name,
                    "imageKey": item.get("iconKey") or None,
                }
            )
    effects.sort(key=lambda value: value["name"])
    records.sort(key=lambda value: (value["band"], value["id"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "records": records,
        "effects": effects,
    }, hidden


def _project_chats(
    document: Mapping[str, Any],
    *,
    staff_by_source: Mapping[str, Mapping[str, Any]],
    band_by_character: Mapping[str, str],
) -> tuple[dict[str, Any], int, int, int]:
    scene_labels = {
        "cashier": "收银",
        "sales": "导购",
        "restocking": "补货",
    }
    role_labels = {**scene_labels, "standby": "待机"}
    records = []
    hidden_scenes = 0
    for item in document.get("records", []):
        if not isinstance(item, dict):
            continue
        characters = []
        character_source_ids = [str(value) for value in item.get("characterIds", [])]
        for source_id in character_source_ids:
            staff = staff_by_source.get(source_id)
            if not staff:
                characters = []
                break
            characters.append(
                {
                    "id": staff["id"],
                    "name": staff["name"],
                    "imageKey": staff.get("imageKey"),
                }
            )
        if len(characters) != 2:
            continue
        scenes = []
        for scene in item.get("scenes", []):
            if not isinstance(scene, dict):
                hidden_scenes += 1
                continue
            kind = str(scene.get("kind") or "")
            label = scene_labels.get(kind)
            lines = [_player_text(line) for line in scene.get("lines", [])]
            if not label or not lines or any(line is None for line in lines):
                hidden_scenes += 1
                continue
            scenes.append({"kind": kind, "label": label, "lines": lines})
        if not scenes:
            continue
        bands = [
            band_by_character[source_id]
            for source_id in character_source_ids
            if source_id in band_by_character
        ]
        band = bands[0] if bands and all(value == bands[0] for value in bands) else ""
        records.append(
            {
                "id": _public_id("chat", item.get("id")),
                "characters": characters,
                "band": band,
                "scenes": scenes,
                "dialogueStatus": str(item.get("speakerMapping") or "ambiguous"),
                "dialogueVerified": bool(item.get("speakerMappingVerified")),
                "dialogueNote": (
                    "每句的说话人尚未从客户端语义中确认；本视图不逐句署名"
                ),
            }
        )

    transcript_groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        signature = json.dumps(record["scenes"], ensure_ascii=False, sort_keys=True)
        transcript_groups.setdefault(signature, []).append(record)
    reused_records = 0
    for group in transcript_groups.values():
        character_pairs = {
            tuple(character["id"] for character in record["characters"])
            for record in group
        }
        if len(character_pairs) < 2:
            continue
        for record in group:
            record["reusedText"] = True
            record["contentNote"] = "包内复用文本，角色与正文可能尚未最终对应"
            reused_records += 1

    monologues = []
    hidden_monologues = 0
    for item in document.get("monologues", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("characterId"))
        staff = staff_by_source.get(source_id)
        if not staff:
            hidden_monologues += len(item.get("roles", []))
            continue
        for role in item.get("roles", []):
            if not isinstance(role, dict):
                hidden_monologues += 1
                continue
            kind = str(role.get("kind") or "")
            label = role_labels.get(kind)
            body = _player_text(role.get("text"))
            if not label or not body:
                hidden_monologues += 1
                continue
            monologues.append(
                {
                    "id": _public_id("monologue", f"{source_id}:{kind}"),
                    "character": {
                        "id": staff["id"],
                        "name": staff["name"],
                        "imageKey": staff.get("imageKey"),
                    },
                    "band": band_by_character.get(source_id, ""),
                    "kind": kind,
                    "role": label,
                    "text": body,
                }
            )
    records.sort(
        key=lambda value: (
            value["band"],
            " × ".join(character["name"] for character in value["characters"]),
            value["id"],
        )
    )
    role_order = {"cashier": 0, "sales": 1, "restocking": 2, "standby": 3}
    monologues.sort(
        key=lambda value: (
            value["character"]["name"],
            role_order.get(value["kind"], 99),
            value["id"],
        )
    )
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "records": records,
            "monologues": monologues,
            "bands": sorted(
                {value for value in band_by_character.values() if value}
            ),
            "scenes": list(scene_labels.values()),
        },
        hidden_monologues,
        hidden_scenes,
        reused_records,
    )


GUIDE_CHAPTER_LABELS = {
    "purchaseShelves": "购买货架",
    "contractGoods": "签约商品",
    "orderDelivery": "下单配送",
    "receiveInventory": "收货入库",
    "restockSales": "补货销售",
    "fever": "FEVER 指南",
}


def _project_guide(document: Mapping[str, Any]) -> tuple[dict[str, Any], int, int]:
    chapters_in = [
        item for item in document.get("chapters", []) if isinstance(item, dict)
    ]
    carousels = document.get("carousels", {})
    if not isinstance(carousels, dict):
        carousels = {}

    def _clean_image(image: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(image, dict):
            return {}
        image_key = image.get("imageKey")
        page_index = image.get("pageIndex")
        if not isinstance(image_key, str) or not image_key:
            return {}
        return {"pageIndex": page_index, "imageKey": image_key}

    chapter_records: list[dict[str, Any]] = []
    total_steps = 0
    total_images = 0
    for chapter in chapters_in:
        key = str(chapter.get("key") or "")
        label = GUIDE_CHAPTER_LABELS.get(key) or str(chapter.get("name") or key or "未命名章节")
        steps_out: list[dict[str, Any]] = []
        for index, step in enumerate(chapter.get("steps", []), start=1):
            if not isinstance(step, dict):
                continue
            primary = _player_text(step.get("primaryText"))
            hint = _player_text(step.get("hintText"))
            if primary is None and key == "fever":
                page_images = [
                    _clean_image(item) for item in (step.get("pageImages", []) or [])
                ]
                page_images = [item for item in page_images if item]
                if not page_images:
                    continue
                steps_out.append(
                    {
                        "sequence": index,
                        "page": str(step.get("page") or ""),
                        "primary": "FEVER 引导",
                        "hint": None,
                        "imageCount": len(page_images),
                        "pageImages": page_images,
                    }
                )
                total_images += len(page_images)
                continue
            if primary is None:
                continue
            steps_out.append(
                {
                    "sequence": index,
                    "page": str(step.get("page") or ""),
                    "primary": primary,
                    "hint": hint,
                }
            )
            total_steps += 1
        chapter_records.append(
            {
                "key": key,
                "name": label,
                "stepCount": len(steps_out),
                "steps": steps_out,
            }
        )
    intro_carousel = carousels.get("intro", {})
    if not isinstance(intro_carousel, dict):
        intro_carousel = {}
    intro_images = [
        _clean_image(item)
        for item in (intro_carousel.get("pageImages", []) or [])
    ]
    intro_images = [item for item in intro_images if item]
    fever_carousel = carousels.get("fever", {})
    if not isinstance(fever_carousel, dict):
        fever_carousel = {}
    fever_images = [
        _clean_image(item)
        for item in (fever_carousel.get("pageImages", []) or [])
    ]
    fever_images = [item for item in fever_images if item]
    if intro_images:
        total_images += len(intro_images)
    if fever_images:
        total_images += len(fever_images)
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "chapters": chapter_records,
            "carousels": {
                "intro": {
                    "referencedBy": intro_carousel.get("referencedBy"),
                    "pageImages": intro_images,
                },
                "fever": {
                    "pageImages": fever_images,
                },
            },
        },
        total_steps,
        total_images,
    )


def _apply_bidirectional_links(
    *,
    goods: Mapping[str, Any],
    furniture: Mapping[str, Any],
    themes: Mapping[str, Any],
    wardrobe: Mapping[str, Any],
    staff: Mapping[str, Any],
    tasks: Mapping[str, Any],
    stages: Mapping[str, Any],
    chats: Mapping[str, Any],
    furniture_by_source: Mapping[str, Mapping[str, Any]],
    goods_public_ids: Mapping[str, str],
) -> dict[str, int]:
    """Add bidirectional Master-derived links between entities, never rewriting into unlock/reward claims."""
    stats = {
        "furnitureThemeLinks": 0,
        "goodsTaskLinks": 0,
        "goodsFurnitureLinks": 0,
        "goodsWardrobeLinks": 0,
        "wardrobeCharacterLinks": 0,
        "characterWardrobeLinks": 0,
        "characterChatLinks": 0,
        "characterStageLinks": 0,
        "characterCustomerLinks": 0,
        "furnitureTaskLinks": 0,
    }

    def _public_id_lookup(items: Iterable[Mapping[str, Any]], field: str = "id") -> dict[str, Mapping[str, Any]]:
        return {str(item.get(field)): item for item in items if isinstance(item, dict)}

    furniture_index = _public_id_lookup(furniture.get("records", []))
    furniture_by_source = furniture_by_source
    goods_index = _public_id_lookup(goods.get("records", []))
    wardrobe_index = _public_id_lookup(wardrobe.get("records", []))
    staff_index = _public_id_lookup(staff.get("records", []))
    stage_index = _public_id_lookup(stages.get("records", []))
    chat_index = _public_id_lookup(chats.get("records", []))
    task_index = _public_id_lookup(tasks.get("records", []))
    theme_index = _public_id_lookup(themes.get("records", []))

    furniture_theme_pairs: list[tuple[str, str]] = []
    for theme in themes.get("records", []):
        if not isinstance(theme, dict):
            continue
        theme_id = str(theme.get("id"))
        for piece in theme.get("requiredFurniture", []) or []:
            fid = str(piece.get("id"))
            if fid in furniture_index:
                furniture_theme_pairs.append((fid, theme_id))
        for piece in theme.get("unlockedFurniture", []) or []:
            fid = str(piece.get("id"))
            if fid in furniture_index:
                furniture_theme_pairs.append((fid, theme_id))

    theme_ids_by_furniture: dict[str, set[str]] = {}
    for fid, tid in furniture_theme_pairs:
        theme_ids_by_furniture.setdefault(fid, set()).add(tid)
        stats["furnitureThemeLinks"] += 1
    for fid, theme_ids in theme_ids_by_furniture.items():
        record = furniture_index.get(fid)
        if record is not None:
            related = record.setdefault("related", {})
            related["themeIds"] = sorted(theme_ids)

    goods_task_pairs: list[tuple[str, str]] = []
    for task in tasks.get("records", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id"))
        for good in goods.get("records", []):
            if not isinstance(good, dict):
                continue
            gid = str(good.get("id"))
            for reward in good.get("rewards", []) or []:
                key = reward.get("key") if isinstance(reward, dict) else None
                if key and key in {r.get("key") for r in task.get("rewards", []) if isinstance(r, dict)}:
                    goods_task_pairs.append((gid, task_id))
        if "previousTaskId" in task and task.get("previousTaskId"):
            related = task.setdefault("related", {})
            related["previousTaskId"] = task.get("previousTaskId")

    task_ids_by_goods: dict[str, set[str]] = {}
    for gid, tid in goods_task_pairs:
        task_ids_by_goods.setdefault(gid, set()).add(tid)
        stats["goodsTaskLinks"] += 1
    for gid, tids in task_ids_by_goods.items():
        record = goods_index.get(gid)
        if record is not None:
            related = record.setdefault("related", {})
            related["taskIds"] = sorted(tids)

    goods_furniture_pairs: list[tuple[str, str]] = []
    for theme in themes.get("records", []):
        if not isinstance(theme, dict):
            continue
        theme_id = str(theme.get("id"))
        for piece in theme.get("requiredFurniture", []) or []:
            fid = str(piece.get("id"))
            if fid in furniture_index:
                furniture_record = furniture_index[fid]
                for good in furniture_record.get("associated", {}).get("goodsIds", []) or []:
                    if good in goods_index:
                        goods_furniture_pairs.append((good, fid))
        for piece in theme.get("unlockedFurniture", []) or []:
            fid = str(piece.get("id"))
            if fid in furniture_index:
                furniture_record = furniture_index[fid]
                for good in furniture_record.get("associated", {}).get("goodsIds", []) or []:
                    if good in goods_index:
                        goods_furniture_pairs.append((good, fid))

    furniture_ids_by_goods: dict[str, set[str]] = {}
    for gid, fid in goods_furniture_pairs:
        furniture_ids_by_goods.setdefault(gid, set()).add(fid)
        stats["goodsFurnitureLinks"] += 1
    for gid, fids in furniture_ids_by_goods.items():
        record = goods_index.get(gid)
        if record is not None:
            related = record.setdefault("related", {})
            related["furnitureIds"] = sorted(fids)

    goods_wardrobe_pairs: list[tuple[str, str]] = []
    for wardrobe_record in wardrobe.get("records", []):
        if not isinstance(wardrobe_record, dict):
            continue
        wardrobe_id = str(wardrobe_record.get("id"))
        for good in wardrobe_record.get("associatedGoods", []) or []:
            gid = str(good.get("id"))
            if gid in goods_index:
                goods_wardrobe_pairs.append((gid, wardrobe_id))
    wardrobe_ids_by_goods: dict[str, set[str]] = {}
    for gid, wid in goods_wardrobe_pairs:
        wardrobe_ids_by_goods.setdefault(gid, set()).add(wid)
        stats["goodsWardrobeLinks"] += 1
    for gid, wids in wardrobe_ids_by_goods.items():
        record = goods_index.get(gid)
        if record is not None:
            related = record.setdefault("related", {})
            related["wardrobeIds"] = sorted(wids)

    wardrobe_to_characters: dict[str, set[str]] = {}
    characters_to_wardrobe: dict[str, set[str]] = {}
    for wardrobe_record in wardrobe.get("records", []):
        if not isinstance(wardrobe_record, dict):
            continue
        wardrobe_id = str(wardrobe_record.get("id"))
        for character in wardrobe_record.get("characters", []) or []:
            cid = str(character.get("id"))
            if cid in staff_index:
                wardrobe_to_characters.setdefault(wardrobe_id, set()).add(cid)
                characters_to_wardrobe.setdefault(cid, set()).add(wardrobe_id)
                stats["wardrobeCharacterLinks"] += 1
    for wid, cids in wardrobe_to_characters.items():
        record = wardrobe_index.get(wid)
        if record is not None:
            related = record.setdefault("related", {})
            related["characterIds"] = sorted(cids)
    for cid, wids in characters_to_wardrobe.items():
        record = staff_index.get(cid)
        if record is not None:
            related = record.setdefault("related", {})
            related["wardrobeIds"] = sorted(wids)
            stats["characterWardrobeLinks"] += 1

    character_chat_pairs: list[tuple[str, str]] = {}
    for chat in chats.get("records", []):
        if not isinstance(chat, dict):
            continue
        chat_id = str(chat.get("id"))
        for character in chat.get("characters", []) or []:
            cid = str(character.get("id"))
            if cid in staff_index:
                character_chat_pairs.setdefault(cid, set()).add(chat_id)
                stats["characterChatLinks"] += 1
    for cid, chat_ids in character_chat_pairs.items():
        record = staff_index.get(cid)
        if record is not None:
            related = record.setdefault("related", {})
            related["chatIds"] = sorted(chat_ids)

    character_stage_pairs: dict[str, set[str]] = {}
    for stage in stages.get("records", []):
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id"))
        for member in stage.get("members", []) or []:
            cid = str(member.get("id"))
            if cid in staff_index:
                character_stage_pairs.setdefault(cid, set()).add(stage_id)
                stats["characterStageLinks"] += 1
    for cid, stage_ids in character_stage_pairs.items():
        record = staff_index.get(cid)
        if record is not None:
            related = record.setdefault("related", {})
            related["stageIds"] = sorted(stage_ids)

    customers_index = _public_id_lookup(chats.get("records", []))
    return stats


def _project_mechanics(document: Mapping[str, Any]) -> dict[str, Any]:
    sections_in = [
        item for item in document.get("sections", []) if isinstance(item, dict)
    ]
    sections_out: list[dict[str, Any]] = []
    for section in sections_in:
        entries_out: list[dict[str, Any]] = []
        for entry in section.get("entries", []) or []:
            if not isinstance(entry, dict):
                continue
            label_raw = entry.get("label")
            label_text = _player_text(label_raw) or _player_text(entry.get("name")) or str(label_raw or entry.get("key") or "")
            e_out: dict[str, Any] = {
                "key": entry.get("key"),
                "label": label_text,
                "value": str(entry.get("rawValue") or ""),
            }
            unit = entry.get("unit")
            if unit:
                e_out["unit"] = unit
            entries_out.append(e_out)
        section_out: dict[str, Any] = {
            "key": str(section.get("key") or ""),
            "name": str(section.get("name") or ""),
            "entries": entries_out,
        }
        for extra in ("customerPools", "roamCustomerPools", "townNpcPools", "decorationKinds", "staffEffectDetails", "attributes", "bgm", "initMap"):
            payload = section.get(extra)
            if isinstance(payload, list):
                cleaned = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    item.pop("_source", None)
                    cleaned.append(item)
                if cleaned:
                    section_out[extra] = cleaned
        sections_out.append(section_out)
    return {"schemaVersion": SCHEMA_VERSION, "sections": sections_out}


TASK_SERIES_FILTERS = {
    "partner": "合伙人",
    "sales": "金牌销售",
    "tycoon": "商业大亨",
    "collector": "收藏家",
    "fashion": "穿搭潮人",
    "fever": "演出家",
    "popular": "小有人气",
    "cost": "消费达人",
    "growth": "店铺成长",
}


def _classify_task_series(chain_name: str) -> str | None:
    for key, label in TASK_SERIES_FILTERS.items():
        if label in chain_name:
            return key
    for alias, mapped in [("初创店主", "店铺成长"), ("资深店主", "店铺成长"), ("传奇店主", "店铺成长")]:
        if alias in chain_name:
            return "growth"
    return None


def _project_tasks_structured(
    document: Mapping[str, Any],
    *,
    goods_names: Mapping[str, str],
    tag_names: Mapping[str, str],
    category_names: Mapping[str, str],
    decoration_names: Mapping[str, str],
    decoration_type_names: Mapping[str, str],
    staff_names: Mapping[str, str],
    clerk_names: Mapping[str, str],
    suit_names: Mapping[str, str],
) -> tuple[dict[str, Any], int]:
    task_types = {
        str(item.get("id")): item
        for item in document.get("taskTypes", [])
        if isinstance(item, dict)
    }
    tab_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="任务") or "任务"
        for item in document.get("tabs", [])
        if isinstance(item, dict)
    }
    reward_items = {
        f"{item.get('rewardType')}:{item.get('id')}": item
        for item in document.get("rewardItems", [])
        if isinstance(item, dict)
    }
    source_records = [item for item in document.get("records", []) if isinstance(item, dict)]
    flat_tasks: dict[str, dict[str, Any]] = {}
    hidden = 0
    for item in source_records:
        definition = task_types.get(str(item.get("taskTypeId")))
        template = _player_text(definition.get("description")) if definition else None
        if not template:
            hidden += 1
            continue
        values = []
        complete = True
        for parameter in item.get("parameters", []):
            if not isinstance(parameter, dict):
                complete = False
                break
            rendered = _task_parameter_text(
                parameter.get("name"), parameter.get("value"),
                goods_names=goods_names, tag_names=tag_names,
                category_names=category_names, decoration_names=decoration_names,
                decoration_type_names=decoration_type_names,
                staff_names=staff_names, clerk_names=clerk_names,
                suit_names=suit_names,
            )
            if rendered is None:
                complete = False
                break
            values.append(rendered)
        if not complete:
            hidden += 1
            continue
        rewards = []
        for reward in item.get("reward", []):
            if not isinstance(reward, dict):
                continue
            kind = str(reward.get("type") or "reward")
            source_item = str(reward.get("itemId") or "item")
            key = _public_id("reward", f"{kind}:{source_item}")
            reward_definition = reward_items.get(f"{kind}:{source_item}")
            name = (
                _player_text(reward_definition.get("name"))
                if reward_definition else None
            ) or goods_names.get(source_item, "奖励物品")
            rewards.append(
                {
                    "key": key,
                    "name": name,
                    "count": _as_number(reward.get("count")),
                }
            )
        source_id = str(item.get("id"))
        condition = _replace_placeholders(template, values)
        task_record = {
            "id": _public_id("task", source_id),
            "category": tab_names.get(str(item.get("taskTabId")), "任务"),
            "condition": condition,
            "rewards": rewards,
            "previousTaskId": str(item.get("predecessorTaskId"))
            if item.get("predecessorTaskId") else None,
        }
        flat_tasks[source_id] = task_record

    chapters_in = [
        item for item in document.get("structuredChapters", []) if isinstance(item, dict)
    ]
    chapters_out: list[dict[str, Any]] = []
    for chapter in chapters_in:
        ch_tasks = []
        for tid in chapter.get("taskIds", []) or []:
            task = flat_tasks.get(str(tid))
            if task:
                ch_tasks.append(task)
        chapters_out.append(
            {
                "id": _public_id("chapter", chapter.get("id")),
                "name": _player_text(chapter.get("name"), fallback=f"章节 {chapter.get('id')}")
                or f"章节 {chapter.get('id')}",
                "taskCount": len(ch_tasks),
                "tasks": ch_tasks,
            }
        )
    chapters_out.sort(key=lambda item: item["id"])

    chains_in = [
        item for item in document.get("structuredAchievementChains", []) if isinstance(item, dict)
    ]
    chains_out: list[dict[str, Any]] = []
    chain_nodes: set[str] = set()
    for chain in chains_in:
        ch_tasks = []
        for tid in chain.get("taskIds", []) or []:
            task = flat_tasks.get(str(tid))
            if task:
                ch_tasks.append(task)
                chain_nodes.add(str(tid))
        if ch_tasks:
            chain_name = _player_text(chain.get("name"), fallback="成就链") or "成就链"
            series_key = _classify_task_series(chain_name)
            chains_out.append(
                {
                    "id": _public_id("chain", chain.get("firstTaskId")),
                    "name": chain_name,
                    "length": len(ch_tasks),
                    "seriesKey": series_key,
                    "series": TASK_SERIES_FILTERS.get(series_key or "", "") if series_key else "",
                    "tasks": ch_tasks,
                }
            )
    chains_out.sort(key=lambda item: (item.get("series", ""), item["id"]))

    series_filters = [
        {"key": key, "label": label}
        for key, label in TASK_SERIES_FILTERS.items()
        if any(ch.get("seriesKey") == key for ch in chains_out)
    ]

    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "chapters": chapters_out,
            "achievementChains": chains_out,
            "seriesFilters": series_filters,
        },
        hidden,
    )


def _validate_player_value(value: Any, *, key: str = "root") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key.startswith("_") or child_key in FORBIDDEN_KEYS:
                raise AnonTokyoPlayerGuideError(f"player output contains a private field: {child_key}")
            _validate_player_value(child, key=child_key)
        return
    if isinstance(value, list):
        for child in value:
            _validate_player_value(child, key=key)
        return
    if not isinstance(value, str):
        return
    if "MasterAT" in value or value.startswith("/") or WINDOWS_ABSOLUTE_PATH.match(value):
        raise AnonTokyoPlayerGuideError(f"player output contains a private value in {key}")
    if key in {"name", "summary", "condition", "category", "label", "reason", "effect"} and RAW_TEXT_KEY.fullmatch(value):
        raise AnonTokyoPlayerGuideError(f"player output contains an unresolved text key in {key}")


def build_anontokyo_player_guide(
    *,
    projection_root: Path,
    output_root: Path,
    formula_policy: Mapping[str, str] | None = None,
) -> AnonTokyoPlayerGuideResult:
    """Build all player-facing datasets behind one small, validated interface."""
    if output_root.exists():
        raise AnonTokyoPlayerGuideError("player guide output already exists")
    manifest, source = _load_projection(projection_root)
    formulas_verified = dict(formula_policy or {}) == VERIFIED_FORMULA_POLICY
    (
        goods,
        goods_names,
        goods_public_ids,
        tag_names,
        category_names,
        hidden_goods,
    ) = _project_goods(
        source["goods.json"], formulas_verified=formulas_verified
    )
    currency_names = {
        str(item.get("id")): name
        for item in source["tasks.json"].get("rewardItems", [])
        if isinstance(item, dict)
        and (name := _player_text(item.get("name")))
    }
    store = _project_store(
        source["progression.json"], currency_names=currency_names
    )
    growth = _project_growth(
        source["progression.json"], currency_names=currency_names
    )
    decoration_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="装饰") or "装饰"
        for item in source["decorations.json"].get("records", [])
        if isinstance(item, dict)
    }
    decoration_type_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="装饰分类")
        or "装饰分类"
        for item in source["decorations.json"].get("subTypes", [])
        if isinstance(item, dict)
    }
    staff_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="角色") or "角色"
        for item in source["staff.json"].get("records", [])
        if isinstance(item, dict)
    }
    clerk_names: dict[str, str] = {}
    for item in source["staff.json"].get("clerks", []):
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        character_name = staff_names.get(str(fields.get("characterID")))
        if character_name:
            clerk_names[str(item.get("id"))] = character_name
    suit_names = {
        str(item.get("id")): _player_text(item.get("name"), fallback="布景") or "布景"
        for item in source["tasks.json"].get("suits", [])
        if isinstance(item, dict)
    }
    tasks, hidden_tasks = _project_tasks(
        source["tasks.json"],
        goods_names=goods_names,
        tag_names=tag_names,
        category_names=category_names,
        decoration_names=decoration_names,
        decoration_type_names=decoration_type_names,
        staff_names=staff_names,
        clerk_names=clerk_names,
        suit_names=suit_names,
    )
    furniture, hidden_furniture, furniture_by_source = _project_furniture(
        source["decorations.json"]
    )
    studio = None
    if "map.json" in source:
        input_summary = manifest.get("inputSummary")
        studio = _project_studio(
            source["map.json"],
            source["decorations.json"],
            furniture_by_source=furniture_by_source,
            store=store,
            catalog_hash=(
                input_summary.get("catalogHash")
                if isinstance(input_summary, dict)
                and isinstance(input_summary.get("catalogHash"), str)
                else None
            ),
        )
    reward_items = {
        f"{item.get('rewardType')}:{item.get('id')}": item
        for item in source["tasks.json"].get("rewardItems", [])
        if isinstance(item, dict)
    }
    for item in source["decorations.json"].get("records", []):
        if not isinstance(item, dict):
            continue
        reward_items.setdefault(
            f"2:{item.get('id')}",
            {
                "name": item.get("name"),
                "iconKey": item.get("mediaKey") or None,
            },
        )
    for item in source["goods.json"].get("records", []):
        if not isinstance(item, dict):
            continue
        reward_items.setdefault(
            f"4:{item.get('id')}",
            {
                "name": item.get("name"),
                "iconKey": item.get("mediaKey") or None,
            },
        )
    themes, unresolved_theme_furniture = _project_themes(
        source["themes.json"],
        furniture_by_source=furniture_by_source,
        reward_items=reward_items,
    )
    staff = _project_staff(source["staff.json"])
    staff_by_public_id = {item["id"]: item for item in staff["records"]}
    staff_by_source = {
        str(item.get("id")): staff_by_public_id[_public_id("staff", item.get("id"))]
        for item in source["staff.json"].get("records", [])
        if isinstance(item, dict)
        and _public_id("staff", item.get("id")) in staff_by_public_id
    }
    wardrobe, hidden_wardrobe = _project_wardrobe(
        source["wardrobe.json"],
        goods_names=goods_names,
        goods_public_ids=goods_public_ids,
        goods_by_public_id={item["id"]: item for item in goods["records"]},
        staff_by_source=staff_by_source,
    )
    inspiration = _project_inspiration(source["inspiration.json"])
    stages, hidden_stages = _project_stages(
        source["stages.json"], staff_by_source=staff_by_source
    )
    band_by_character: dict[str, str] = {}
    for stage in source["stages.json"].get("records", []):
        if not isinstance(stage, dict):
            continue
        band_name = _player_text(stage.get("bandName"))
        if not band_name:
            continue
        for source_id in stage.get("memberIds", []):
            band_by_character[str(source_id)] = band_name
    staff_by_identity: dict[str, Mapping[str, Any]] = {}
    staff_source_by_identity: dict[str, str] = {}
    for item in source["staff.json"].get("records", []):
        if not isinstance(item, dict):
            continue
        identity = str(item.get("identityNumber"))
        public_staff = staff_by_source.get(str(item.get("id")))
        if public_staff and identity not in ("", "None"):
            staff_by_identity[identity] = public_staff
            staff_source_by_identity[identity] = str(item.get("id"))
    customers, hidden_customers = _project_customers(
        source["progression.json"],
        staff_by_identity=staff_by_identity,
        staff_source_by_identity=staff_source_by_identity,
        band_by_character=band_by_character,
        tag_names=tag_names,
        goods=goods,
    )
    chats, hidden_monologues, hidden_chat_scenes, reused_chat_combinations = _project_chats(
        source["chats.json"],
        staff_by_source=staff_by_source,
        band_by_character=band_by_character,
    )
    guide, guide_steps, guide_images = _project_guide(source["guide.json"])
    mechanics = _project_mechanics(source["mechanics.json"])
    tasks_structured, hidden_structured_tasks = _project_tasks_structured(
        source["tasks.json"],
        goods_names=goods_names,
        tag_names=tag_names,
        category_names=category_names,
        decoration_names=decoration_names,
        decoration_type_names=decoration_type_names,
        staff_names=staff_names,
        clerk_names=clerk_names,
        suit_names=suit_names,
    )
    bidirectional_stats = _apply_bidirectional_links(
        goods=goods,
        furniture=furniture,
        themes=themes,
        wardrobe=wardrobe,
        staff=staff,
        tasks=tasks,
        stages=stages,
        chats=chats,
        furniture_by_source=furniture_by_source,
        goods_public_ids=goods_public_ids,
    )
    documents = {
        "store.json": store,
        "growth.json": growth,
        "goods.json": goods,
        "customers.json": customers,
        "wardrobe.json": wardrobe,
        "inspiration.json": inspiration,
        "furniture.json": furniture,
        "themes.json": themes,
        "stages.json": stages,
        "chats.json": chats,
        "tasks.json": tasks,
        "staff.json": staff,
        "guide.json": guide,
        "mechanics.json": mechanics,
    }
    if studio is not None:
        documents["studio.json"] = studio
    tasks["chapters"] = tasks_structured["chapters"]
    tasks["achievementChains"] = tasks_structured["achievementChains"]
    tasks["seriesFilters"] = tasks_structured["seriesFilters"]
    for document in documents.values():
        document["sourceReleaseId"] = manifest.get("sourceReleaseId")
        document["generatedAt"] = manifest.get("generatedAt")
        _validate_player_value(document)

    report = {
        "recordCounts": {
            "storeLevels": len(store["levels"]),
            "playerLevels": len(growth["records"]),
            "warehouseSteps": len(growth["warehouseSteps"]),
            "safeDepositSteps": len(growth["safeDepositSteps"]),
            "goods": len(goods["records"]),
            "characterCustomers": len(customers["records"]),
            "wardrobe": len(wardrobe["records"]),
            "inspirationTiers": len(inspiration["records"]),
            "furniture": len(furniture["records"]),
            "themes": len(themes["records"]),
            "stages": len(stages["records"]),
            "chatCombinations": len(chats["records"]),
            "monologues": len(chats["monologues"]),
            "tasks": len(tasks["records"]),
            "characters": len(staff["records"]),
            "guideChapters": len(guide["chapters"]),
            "guideSteps": guide_steps,
            "guideImages": guide_images,
            "studioFurniture": len(studio["furniture"]) if studio else 0,
        },
        "hiddenTasks": hidden_tasks,
        "hiddenGoods": hidden_goods,
        "hiddenCustomers": hidden_customers,
        "hiddenWardrobe": hidden_wardrobe,
        "hiddenFurniture": hidden_furniture,
        "unresolvedThemeFurniture": unresolved_theme_furniture,
        "hiddenStages": hidden_stages,
        "hiddenMonologues": hidden_monologues,
        "hiddenChatScenes": hidden_chat_scenes,
        "reusedChatCombinations": reused_chat_combinations,
        "wardrobeWithVerifiedAttribution": sum(
            1 for item in wardrobe["records"] if item.get("attributionVerified")
        ),
        "wardrobeUnconfirmedAttribution": sum(
            1 for item in wardrobe["records"] if not item.get("attributionVerified")
        ),
        "charactersWithUnverifiedStats": sum(
            1 for item in staff["records"] if not item.get("statsVerified")
        ),
        "bidirectionalLinks": bidirectional_stats,
        "furnitureWithImages": sum(
            1 for item in furniture["records"] if item.get("imageKey")
        ),
        "charactersWithImages": sum(
            1 for item in staff["records"] if item.get("imageKey")
        ),
        "themesWithImages": sum(
            1 for item in themes["records"] if item.get("imageKey")
        ),
        "stagesWithImages": sum(
            1
            for item in stages["records"]
            if isinstance(item.get("music"), dict)
            and item["music"].get("imageKey")
        ),
        "feverEffects": len(stages["effects"]),
        "formulaCapabilities": {
            "goodsProfit": "verified" if formulas_verified else "blocked",
            "goodsProfitPerTime": "verified" if formulas_verified else "blocked",
            "wardrobeCharacterAttribution": "verified",
            "characterStatsSemantics": "blocked",
            "chatSpeakerMapping": "blocked",
        },
    }
    parent = output_root.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.partial-", dir=parent))
    except OSError as exc:
        raise AnonTokyoPlayerGuideError("player guide output cannot be prepared") from exc
    try:
        file_index: dict[str, dict[str, Any]] = {}
        output_files = (*OUTPUT_FILES, *(("studio.json",) if studio is not None else ()))
        for name in output_files:
            data = _json_bytes(documents[name])
            (stage / name).write_bytes(data)
            file_index[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        player_manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "sourceReleaseId": manifest.get("sourceReleaseId"),
            "generatedAt": manifest.get("generatedAt"),
            "recordCounts": report["recordCounts"],
            "formulaCapabilities": report["formulaCapabilities"],
            "files": file_index,
        }
        _validate_player_value(player_manifest)
        (stage / "manifest.json").write_bytes(_json_bytes(player_manifest))
        os.replace(stage, output_root)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, AnonTokyoPlayerGuideError):
            raise
        raise AnonTokyoPlayerGuideError("player guide output cannot be written") from exc

    return AnonTokyoPlayerGuideResult(
        output_root=output_root,
        manifest=player_manifest,
        report=report,
        files=tuple(output_root / name for name in ("manifest.json", *output_files)),
    )
