"""Build evidence-backed private AnonTokyo guide projections from local data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.anontokyo_studio import AnonTokyoStudioError, build_studio_map_document
from tools.anontokyo_staff_assignment import build_staff_assignment_evidence


SCHEMA_VERSION = 1
LOCALES = ("zh-CN", "zh-TW", "ja", "en")
TEXT_FIELDS = {
    "zh-CN": "_simplifiedChinese",
    "zh-TW": "_traditionalChinese",
    "ja": "_japanese",
    "en": "_english",
}
RELEASE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
OUTPUT_FILES = (
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
    "media-manifest.json",
)
REQUIRED_TABLES = (
    "MasterText",
    "MasterBand",
    "MasterATGoods",
    "MasterATGoodCategory",
    "MasterATTag",
    "MasterATStore",
    "MasterATDecoration",
    "MasterATDecorationMainType",
    "MasterATDecorationSubType",
    "MasterATTaskMain",
    "MasterATTaskType",
    "MasterATCharacter",
    "MasterATAvatar",
    "MasterATCharPassiveAbility",
    "MasterATRoleJob",
    "MasterATStage",
    "MasterATStageBuff",
    "MasterATStageMusic",
    "MasterATCharChat",
    "MasterATCharChatManage",
    "MasterATMonologueChar",
    "MasterATMonologueMain",
    "MasterATReloading",
    "MasterATReplacementparts",
    "MasterATInspiration",
    "MasterATGuide",
    "MasterATImageGuide",
    "MasterATGlobal",
    "MasterATCustomer",
    "MasterATCustomerArray",
    "MasterATRoamCustomer",
    "MasterATRoamCustomerArray",
    "MasterATTownNpc",
    "MasterATTownNpcArray",
    "MasterATAttribute",
    "MasterATBgmMusic",
    "MasterATInitMapObjects",
)
OPTIONAL_TABLES = (
    "MasterATGoodsToReloading",
    "MasterATPlayer",
    "MasterATWarehouse",
    "MasterATSafedepositBox",
    "MasterATShelf",
    "MasterATBDCustomer",
    "MasterATBDCustomerLv",
    "MasterATDelivery",
    "MasterATDeliveryman",
    "MasterATDeliverySkill",
    "MasterATHelper",
    "MasterATHelperSkill",
    "MasterATTaskTabs",
    "MasterATChapterTask",
    "MasterATDailyTask",
    "MasterATAchievement",
    "MasterATAchievementTask",
    "MasterATReward",
    "MasterATCurrencyType",
    "MasterATSuitTheme",
    "MasterATClerk",
    "MasterATStaticDecoration",
)
FORMULA_CAPABILITIES = {
    "goodsProfit": "blocked",
    "goodsProfitPerTime": "blocked",
    "customerPurchaseModel": "blocked",
    "decorationOutcome": "blocked",
    "layoutOptimization": "blocked",
    "staffOptimization": "blocked",
}


class AnonTokyoProjectionError(RuntimeError):
    """Raised when a private projection cannot be built safely."""


@dataclass(frozen=True)
class AnonTokyoProjectionResult:
    output_root: Path
    manifest: Mapping[str, Any]
    files: tuple[Path, ...]


class _TextIndex:
    def __init__(self, rows: Sequence[Mapping[str, Any]]):
        self._rows = {str(row["_id"]): row for row in rows}

    def resolve(self, key: Any) -> dict[str, Any]:
        key_text = "" if key is None else str(key)
        row = self._rows.get(key_text)
        values: dict[str, str] = {}
        status: dict[str, str] = {}
        for locale, field in TEXT_FIELDS.items():
            value = row.get(field) if row else None
            if isinstance(value, str) and value.strip():
                values[locale] = value
                status[locale] = "verified"
            else:
                values[locale] = key_text
                status[locale] = "missing"
        return {
            "key": key_text,
            "values": values,
            "status": status,
        }


def _stable_id(value: Any, *, table: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise AnonTokyoProjectionError(f"{table} contains an invalid ID")
    text = str(value)
    if not text:
        raise AnonTokyoProjectionError(f"{table} contains an empty ID")
    return text


def _load_table(master_root: Path, name: str, *, required: bool) -> list[dict[str, Any]]:
    path = master_root / f"{name}.json"
    if not path.is_file():
        if required:
            raise AnonTokyoProjectionError(f"required Master table is missing: {name}")
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnonTokyoProjectionError(f"Master table is unreadable: {name}") from exc
    rows = document.get("_allData") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise AnonTokyoProjectionError(f"Master table _allData must be an array: {name}")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise AnonTokyoProjectionError(f"Master table contains a non-object row: {name}")
        identity = _stable_id(row.get("_id"), table=name)
        if identity in ids:
            raise AnonTokyoProjectionError(f"Master table contains duplicate ID {identity}: {name}")
        ids.add(identity)
        normalized.append(dict(row))
    return normalized


def _table_sha256(master_root: Path, name: str) -> str:
    try:
        return hashlib.sha256((master_root / f"{name}.json").read_bytes()).hexdigest()
    except OSError as exc:
        raise AnonTokyoProjectionError(f"Master table is unreadable: {name}") from exc


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


def _source(table: str, row: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {
        "sourceTable": table,
        "sourceId": str(row["_id"]),
        "sourceFields": sorted(field for field in fields if field in row),
    }


def _status(*, warnings: Sequence[str], names: Sequence[Mapping[str, Any]] = ()) -> str:
    if warnings:
        return "partial"
    for name in names:
        if any(value != "verified" for value in name.get("status", {}).values()):
            return "partial"
    return "verified"


def _quality(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    result = {"verified": 0, "partial": 0, "blocked": 0}
    for record in records:
        value = str(record.get("interpretationStatus", "partial"))
        result[value if value in result else "partial"] += 1
    return result


def _base_document(
    *,
    release_id: str,
    generated_at: str,
    tables: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceReleaseId": release_id,
        "generatedAt": generated_at,
        "sourceTables": sorted(tables),
        "qualitySummary": _quality(records),
        "records": list(records),
        **extra,
    }


def _ref_status(identity: Any, index: Mapping[str, Any], label: str) -> tuple[str | None, list[str]]:
    if identity in (None, "", 0, "0"):
        return None, []
    text = str(identity)
    if text not in index:
        return text, [f"unresolved_{label}:{text}"]
    return text, []


def _build_goods(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    categories = {str(row["_id"]): row for row in tables["MasterATGoodCategory"]}
    tags = {str(row["_id"]): row for row in tables["MasterATTag"]}
    records: list[dict[str, Any]] = []
    media: set[str] = set()
    category_records = []
    for row in categories.values():
        name = text.resolve(row.get("_suitName"))
        icon = str(row.get("_icon") or "")
        if icon:
            media.add(icon)
        category_records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "iconKey": icon or None,
                "subType": row.get("_subType"),
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATGoodCategory", row, row.keys()),
            }
        )
    tag_records = []
    for row in tags.values():
        name = text.resolve(row.get("_tagName"))
        icon = str(row.get("_iconPathName") or "")
        if icon:
            media.add(icon)
        tag_records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "iconKey": icon or None,
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATTag", row, row.keys()),
            }
        )
    for row in tables["MasterATGoods"]:
        warnings: list[str] = []
        category_id, category_warnings = _ref_status(
            row.get("_categoryId"), categories, "category"
        )
        warnings.extend(category_warnings)
        tag_ids: list[str] = []
        for raw_tag in row.get("_tagID") or []:
            tag_id, tag_warnings = _ref_status(raw_tag, tags, "tag")
            if tag_id:
                tag_ids.append(tag_id)
            warnings.extend(tag_warnings)
        name = text.resolve(row.get("_name"))
        address = str(row.get("_address") or "")
        if address:
            media.add(address)
        records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "categoryId": category_id,
                "tagIds": tag_ids,
                "mediaKey": address or None,
                "purchase": {
                    "itemCount": row.get("_buyItemCount"),
                    "cost": row.get("_buyItemCost"),
                },
                "saleCoinCounts": list(row.get("_sellCoinCount") or []),
                "saleExpCounts": list(row.get("_sellExpCount") or []),
                "deliveryDuration": row.get("_deliveryDuration"),
                "enhanceCosts": list(row.get("_enhanceCost") or []),
                "unlock": {
                    "type": row.get("_unlockType"),
                    "count": row.get("_unlockCount"),
                    "costType": row.get("_unlockCostType"),
                    "costCount": row.get("_unlockCostCount"),
                },
                "visible": bool(row.get("_isShow")),
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings, names=[name]),
                **_source("MasterATGoods", row, row.keys()),
            }
        )
    records.sort(key=lambda item: item["id"])
    for category in category_records:
        category["goodsIds"] = [
            item["id"] for item in records if item["categoryId"] == category["id"]
        ]
    for tag in tag_records:
        tag["goodsIds"] = [item["id"] for item in records if tag["id"] in item["tagIds"]]
    document = _base_document(
        release_id="",
        generated_at="",
        tables=("MasterATGoods", "MasterATGoodCategory", "MasterATTag"),
        records=records,
        categories=sorted(category_records, key=lambda item: item["id"]),
        tags=sorted(tag_records, key=lambda item: item["id"]),
    )
    return document, media


def _build_decorations(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    main_types = {str(row["_id"]): row for row in tables["MasterATDecorationMainType"]}
    sub_types = {str(row["_id"]): row for row in tables["MasterATDecorationSubType"]}
    media: set[str] = set()

    def type_records(rows: Mapping[str, Mapping[str, Any]], table: str, name_field: str) -> list[dict[str, Any]]:
        result = []
        for row in rows.values():
            name = text.resolve(row.get(name_field))
            icon = str(row.get("_iconPath") or "")
            if icon:
                media.add(icon)
            result.append(
                {
                    "id": str(row["_id"]),
                    "name": name,
                    "iconKey": icon or None,
                    "type": row.get("_type"),
                    "subType": row.get("_subType"),
                    "areaType": row.get("_areaType"),
                    "order": row.get("_order"),
                    "visible": bool(row.get("_isShow")),
                    "interpretationStatus": _status(warnings=[], names=[name]),
                    **_source(table, row, row.keys()),
                }
            )
        return sorted(result, key=lambda item: item["id"])

    records: list[dict[str, Any]] = []
    for row in tables["MasterATDecoration"]:
        warnings: list[str] = []
        type_id, type_warnings = _ref_status(row.get("_type"), main_types, "decoration_type")
        sub_type_id, sub_warnings = _ref_status(
            row.get("_subType"), sub_types, "decoration_subtype"
        )
        warnings.extend(type_warnings)
        warnings.extend(sub_warnings)
        name = text.resolve(row.get("_productNameID"))
        media_key = str(row.get("_iconPath") or row.get("_address") or "")
        address = str(row.get("_address") or "")
        scene_media_key = None
        if address.endswith("/Unsale/Warehouse"):
            scene_media_key = "AT_Map_Outdoor_Warehouse_Full"
        elif address.endswith("/Stage/Stage0"):
            scene_media_key = "AT_Map_Stage1_Img_Bottom"
        elif address.endswith("/Stage/Stage1"):
            scene_media_key = "AT_Map_Stage2_Img_Bottom"
        if media_key:
            media.add(media_key)
        if scene_media_key:
            media.add(scene_media_key)
        records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "typeId": type_id,
                "subTypeId": sub_type_id,
                "mediaKey": media_key or None,
                "sceneMediaKey": scene_media_key,
                "size": row.get("_size"),
                "direction": row.get("_direction"),
                "buyDirection": row.get("_buyDirection"),
                "purchase": {
                    "itemId": row.get("_buyItemId"),
                    "itemCount": row.get("_buyItemCount"),
                },
                "sale": {
                    "itemId": row.get("_sellItemId"),
                    "itemCount": row.get("_sellItemCount"),
                },
                "popularity": {
                    "id": row.get("_popularityId"),
                    "count": row.get("_popularityCount"),
                },
                "condition": {
                    "type": row.get("_conditionType"),
                    "value": row.get("_conditionValue"),
                },
                "limit": row.get("_maxLimitCount"),
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings, names=[name]),
                **_source("MasterATDecoration", row, row.keys()),
            }
        )
    records.sort(key=lambda item: item["id"])
    document = _base_document(
        release_id="",
        generated_at="",
        tables=("MasterATDecoration", "MasterATDecorationMainType", "MasterATDecorationSubType"),
        records=records,
        mainTypes=type_records(main_types, "MasterATDecorationMainType", "_nameId"),
        subTypes=type_records(sub_types, "MasterATDecorationSubType", "_nameId"),
    )
    return document, media


def _simple_records(table: str, rows: Sequence[Mapping[str, Any]], text: _TextIndex) -> list[dict[str, Any]]:
    name_fields = (
        "_productNameID",
        "_deliveryName",
        "_deliverymanNameID",
        "_helperName",
        "_deliverySkillName",
        "_suitName",
        "_nameID",
    )
    result = []
    for row in rows:
        name_key = next((row[field] for field in name_fields if row.get(field) not in (None, "")), None)
        name = text.resolve(name_key) if name_key is not None else None
        result.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "fields": {key.removeprefix("_"): value for key, value in row.items() if key != "_id"},
                "interpretationStatus": _status(warnings=[], names=[name] if name else []),
                **_source(table, row, row.keys()),
            }
        )
    return sorted(result, key=lambda item: item["id"])


def _build_progression(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    groups = {
        "storeLevels": "MasterATStore",
        "playerLevels": "MasterATPlayer",
        "warehouses": "MasterATWarehouse",
        "safeDepositBoxes": "MasterATSafedepositBox",
        "shelves": "MasterATShelf",
        "characterCustomers": "MasterATBDCustomer",
        "characterCustomerLevels": "MasterATBDCustomerLv",
        "deliveries": "MasterATDelivery",
        "deliveryPeople": "MasterATDeliveryman",
        "deliverySkills": "MasterATDeliverySkill",
        "helpers": "MasterATHelper",
    }
    extra: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    media: set[str] = set()
    for key, table in groups.items():
        values = _simple_records(table, tables.get(table, []), text)
        for value in values:
            value["entityType"] = key
            for field in ("iconPath", "address", "defaultAvatar"):
                raw = value["fields"].get(field)
                if isinstance(raw, str) and raw:
                    media.add(raw)
        extra[key] = values
        records.extend(values)
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=tuple(groups.values()),
            records=records,
            **extra,
        ),
        media,
    )


def _build_wardrobe(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    goods_relations: dict[str, set[str]] = {}
    for relation in tables.get("MasterATGoodsToReloading", []):
        goods = relation.get("_goodsList") or []
        wardrobe = relation.get("_reloadingID") or []
        if not isinstance(goods, list) or not isinstance(wardrobe, list):
            continue
        for goods_id, wardrobe_id in zip(goods, wardrobe):
            goods_relations.setdefault(str(wardrobe_id), set()).add(str(goods_id))

    parts_index = {
        str(row["_id"]): row for row in tables["MasterATReplacementparts"]
    }
    char_index = {str(row["_id"]): row for row in tables["MasterATCharacter"]}

    def _character_from_path(path: str) -> str | None:
        match = re.search(r"/Char/([^/]+)/", path or "")
        return match.group(1) if match else None

    def _resolve_attribution(row: Mapping[str, Any]) -> dict[str, Any]:
        can_use = [str(value) for value in row.get("_canUseChar") or []]
        path_char_names: set[str] = set()
        unresolved_parts: list[str] = []
        for spine_id in row.get("_spineparent") or []:
            part = parts_index.get(str(spine_id))
            if part is None:
                unresolved_parts.append(str(spine_id))
                continue
            char_name = _character_from_path(part.get("_pathName", ""))
            if char_name:
                path_char_names.add(char_name)
        can_use_names: set[str] = set()
        for cid in can_use:
            char_row = char_index.get(cid)
            if not char_row:
                continue
            master_name = str(char_row.get("_name", ""))
            normalized = re.sub(r"^(?:atcharacter_|character_)", "", master_name)
            if normalized:
                can_use_names.add(normalized)
        agreement = (
            "agreed"
            if can_use_names and path_char_names and can_use_names == path_char_names
            else "disagreed"
            if can_use_names and path_char_names and can_use_names != path_char_names
            else "canuse_only"
            if can_use_names
            else "path_only"
            if path_char_names
            else "unresolved"
        )
        warnings: list[str] = []
        if unresolved_parts:
            warnings.append(f"unresolved_replacementparts:{','.join(unresolved_parts)}")
        if agreement == "disagreed":
            warnings.append(
                "wardrobe_attribution_disagreement:"
                f"canuse={sorted(can_use_names)} path={sorted(path_char_names)}"
            )
        if agreement == "unresolved":
            warnings.append("wardrobe_attribution_unresolved")
        verified = agreement in ("agreed", "canuse_only", "path_only")
        return {
            "characterIds": can_use,
            "charactersByCanUse": sorted(can_use_names),
            "charactersByPath": sorted(path_char_names),
            "characterAttributionStatus": agreement,
            "characterAttributionVerified": verified,
            "warnings": warnings,
        }

    records = []
    media: set[str] = set()
    for row in tables["MasterATReloading"]:
        name = text.resolve(row.get("_name"))
        icon = str(row.get("_iconPath") or "")
        if icon:
            media.add(icon)
        attribution = _resolve_attribution(row)
        attribution_warnings = attribution.pop("warnings")
        record_warnings: list[str] = list(attribution_warnings)
        records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "type": row.get("_spineType"),
                "iconKey": icon or None,
                "rarity": row.get("_rarity"),
                "popularity": row.get("_popularity"),
                "goodsIds": sorted(goods_relations.get(str(row["_id"]), set())),
                "visible": bool(row.get("_isShow")),
                **attribution,
                "warnings": sorted(set(record_warnings)),
                "interpretationStatus": _status(
                    warnings=record_warnings, names=[name]
                ),
                **_source("MasterATReloading", row, row.keys()),
            }
        )
    records.sort(key=lambda item: item["id"])
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterATReloading", "MasterATReplacementparts", "MasterATGoodsToReloading"),
            records=records,
        ),
        media,
    )


def _build_inspiration(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    del text
    records = []
    for row in tables["MasterATInspiration"]:
        parts = str(row.get("_inspirationRange") or "").split(",")
        if len(parts) != 2:
            raise AnonTokyoProjectionError("MasterATInspiration contains an invalid range")
        try:
            minimum, maximum = (int(part.strip()) for part in parts)
            purchase_count = int(row.get("_purchaseNum"))
            extra_chance = int(str(row.get("_extraPurchase")))
        except (TypeError, ValueError) as exc:
            raise AnonTokyoProjectionError(
                "MasterATInspiration contains an invalid tier"
            ) from exc
        if minimum < 0 or maximum < minimum or purchase_count < 0 or not 0 <= extra_chance <= 100:
            raise AnonTokyoProjectionError("MasterATInspiration contains an invalid tier")
        records.append(
            {
                "id": str(row["_id"]),
                "range": {"minimum": minimum, "maximum": maximum},
                "purchaseCount": purchase_count,
                "extraPurchaseChance": extra_chance,
                "interpretationStatus": "verified",
                **_source("MasterATInspiration", row, row.keys()),
            }
        )
    records.sort(key=lambda item: (item["range"]["minimum"], item["id"]))
    for previous, current in zip(records, records[1:]):
        if current["range"]["minimum"] != previous["range"]["maximum"] + 1:
            raise AnonTokyoProjectionError(
                "MasterATInspiration ranges must be contiguous"
            )
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterATInspiration",),
            records=records,
        ),
        set(),
    )


GUIDE_CHAPTERS = (
    ("purchaseShelves", "购买货架"),
    ("contractGoods", "签约商品"),
    ("orderDelivery", "下单配送"),
    ("receiveInventory", "收货入库"),
    ("restockSales", "补货销售"),
    ("fever", "FEVER 指南"),
)


def _build_guide(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    image_index = {row.get("_carouselId"): {} for row in tables["MasterATImageGuide"]}
    for row in tables["MasterATImageGuide"]:
        cid = row.get("_carouselId")
        image_index.setdefault(cid, {})[row.get("_pageIndex")] = row

    def _clean_guide_image_key(raw_key: str) -> str:
        stripped = raw_key.rsplit("/", 1)[-1]
        return stripped if stripped else raw_key

    carousel_records: dict[int, list[dict[str, Any]]] = {}
    media: set[str] = set()
    for carousel_id, pages in image_index.items():
        if carousel_id is None:
            continue
        ordered_pages = [
            pages[index] for index in sorted(pages.keys()) if index in pages
        ]
        page_records: list[dict[str, Any]] = []
        for page in ordered_pages:
            raw_key = str(page.get("_imageKey") or "")
            clean_key = _clean_guide_image_key(raw_key) if raw_key else ""
            if clean_key:
                media.add(clean_key)
            page_records.append(
                {
                    "pageIndex": page.get("_pageIndex"),
                    "imageKey": clean_key or None,
                    "interpretationStatus": "verified" if clean_key else "partial",
                    **_source("MasterATImageGuide", page, ("_imageKey",)),
                }
            )
        carousel_records[int(carousel_id)] = page_records

    chapters: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in GUIDE_CHAPTERS}
    warnings: list[str] = []
    step_records: list[dict[str, Any]] = []
    for row in tables["MasterATGuide"]:
        source_id = str(row.get("_id"))
        group = row.get("_group")
        page = str(row.get("_page") or "")
        text_id = str(row.get("_textId") or "")
        hint_id = str(row.get("_hintId") or "")
        primary_text = text.resolve(text_id) if text_id not in ("", "-") else None
        hint_text = text.resolve(hint_id) if hint_id not in ("", "-") else None
        carousel_id = row.get("_carouselId")
        chapter_key = None
        for index, (key, _) in enumerate(GUIDE_CHAPTERS[:5], start=1):
            if group == index:
                chapter_key = key
                break
        record_warnings: list[str] = []
        if primary_text is None and not (text_id in ("", "-") and chapter_key == "fever"):
            if text_id not in ("", "-"):
                record_warnings.append(f"unresolved_guide_text:{text_id}")
        record = {
            "id": source_id,
            "page": page,
            "frameType": row.get("_frameType"),
            "primaryText": primary_text,
            "hintText": hint_text,
            "carouselId": carousel_id,
            "warnings": sorted(set(record_warnings)),
            "interpretationStatus": _status(
                warnings=record_warnings,
                names=[primary_text] if primary_text else [],
            ),
            **_source("MasterATGuide", row, ("_page", "_frameType", "_textId", "_hintId", "_carouselId", "_group")),
        }
        step_records.append(record)
        if chapter_key and chapter_key != "fever":
            chapters[chapter_key].append(record)
        if record_warnings:
            warnings.extend(record_warnings)

    fever_pages = carousel_records.get(2, [])
    fever_record: dict[str, Any] = {
        "id": "fever",
        "page": "FEVERCarousel",
        "frameType": 4,
        "primaryText": None,
        "hintText": None,
        "carouselId": 2,
        "pageImages": fever_pages,
        "warnings": [],
        "interpretationStatus": "partial" if not fever_pages else "verified",
    }
    chapters["fever"] = [fever_record]
    intro_record = next(
        (item for item in step_records if item.get("carouselId") == 1), None
    )
    intro_pages = carousel_records.get(1, [])

    chapter_records = []
    for key, label in GUIDE_CHAPTERS:
        steps = chapters[key]
        chapter_records.append(
            {
                "key": key,
                "name": label,
                "stepCount": len(steps),
                "imageCount": sum(
                    1
                    for step in steps
                    if step.get("pageImages") or step.get("carouselId")
                ),
                "steps": steps,
            }
        )
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterATGuide", "MasterATImageGuide"),
            records=sorted(step_records, key=lambda item: item["id"]),
            chapters=chapter_records,
            carousels={
                "intro": {
                    "carouselId": 1,
                    "imageCount": len(intro_pages),
                    "pageImages": intro_pages,
                    "referencedBy": (
                        intro_record["id"] if intro_record else None
                    ),
                },
                "fever": {
                    "carouselId": 2,
                    "imageCount": len(fever_pages),
                    "pageImages": fever_pages,
                    "referencedBy": None,
                },
            },
        ),
        media,
    )


def _parse_reward(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    result = []
    for group in str(value).split(";"):
        parts = [part.strip() for part in group.split(",")]
        result.append(
            {
                "raw": group,
                "type": parts[0] if len(parts) > 0 else None,
                "itemId": parts[1] if len(parts) > 1 else None,
                "count": parts[2] if len(parts) > 2 else None,
            }
        )
    return result


MECHANICS_CAUTION_FIELDS = frozenset(
    {
        "fever_customer_spawn_rate",
        "fever_drop_interval",
        "fever_full_drop_time",
        "fever_refresh_interval",
        "bang_customer_base_rate",
        "bang_customer_max_rate",
        "bang_customer_rate_increament",
        "bang_customer_spawn_time",
        "bang_customer_hard_pity_timer",
        "bang_customer_offline_threshold",
        "bang_customer_offline_threshold_count",
        "bang_customer_offline_threshold_window",
        "regular_customer_spawn_rate",
        "roam_customer_spawn_rate",
        "monologue_click_cooldown_time",
    }
)


def _build_mechanics(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    customer_index: dict[str, dict[str, Any]] = {}
    customer_records: list[dict[str, Any]] = []
    customer_pool_records: list[dict[str, Any]] = []

    customer_index = {str(r["_id"]): r for r in tables["MasterATCustomer"]}
    for row in tables["MasterATCustomer"]:
        customer_records.append({
            "id": str(row["_id"]),
            "level": _as_number(row.get("_customerLv")),
            "minStayDuration": _as_number(row.get("_minStayDuration")),
            "maxStayDuration": _as_number(row.get("_maxStayDuration")),
            "basePurchaseCount": _as_number(row.get("_basePurchaseCount")),
            "purchaseQuantity": _as_number(row.get("_purchaseQuantity")),
            "guidedShopping": bool(row.get("_guidedShopping")),
            "defaultAvatar": list(row.get("_defaultAvatar") or []),
            "_source": _source("MasterATCustomer", row, list(row.keys())),
        })
    for row in tables["MasterATCustomerArray"]:
        levels = [int(value) for value in (row.get("_customerLevelArray") or [])]
        resolved: list[dict[str, Any]] = []
        for level_id in levels:
            level_row = customer_index.get(str(level_id))
            if not level_row:
                continue
            resolved.append({
                "id": str(level_row["_id"]),
                "level": _as_number(level_row.get("_customerLv")),
                "minStayDuration": _as_number(level_row.get("_minStayDuration")),
                "maxStayDuration": _as_number(level_row.get("_maxStayDuration")),
                "basePurchaseCount": _as_number(level_row.get("_basePurchaseCount")),
            })
        customer_pool_records.append({
            "id": str(row["_id"]),
            "size": len(resolved),
            "levels": resolved,
            "_source": _source("MasterATCustomerArray", row, ("_id", "_customerLevelArray")),
        })

    roam_customer_records: list[dict[str, Any]] = []
    roam_pool_records: list[dict[str, Any]] = []
    roam_index = {str(r["_id"]): r for r in tables["MasterATRoamCustomer"]}
    for row in tables["MasterATRoamCustomer"]:
        roam_customer_records.append({
            "id": str(row["_id"]),
            "level": _as_number(row.get("_customerLv")),
            "minStayDuration": _as_number(row.get("_minStayDuration")),
            "maxStayDuration": _as_number(row.get("_maxStayDuration")),
            "basePurchaseCount": _as_number(row.get("_basePurchaseCount")),
            "purchaseQuantity": _as_number(row.get("_purchaseQuantity")),
            "guidedShopping": bool(row.get("_guidedShopping")),
            "defaultAvatar": list(row.get("_defaultAvatar") or []),
            "_source": _source("MasterATRoamCustomer", row, list(row.keys())),
        })
    for row in tables["MasterATRoamCustomerArray"]:
        levels = [int(value) for value in (row.get("_roamCustomerLevelArray") or [])]
        resolved = []
        for level_id in levels:
            level_row = roam_index.get(str(level_id))
            if not level_row:
                continue
            resolved.append({
                "id": str(level_row["_id"]),
                "level": _as_number(level_row.get("_customerLv")),
            })
        roam_pool_records.append({
            "id": str(row["_id"]),
            "size": len(resolved),
            "levels": resolved,
            "_source": _source("MasterATRoamCustomerArray", row, ("_id", "_roamCustomerLevelArray")),
        })

    town_npc_records: list[dict[str, Any]] = []
    town_pool_records: list[dict[str, Any]] = []

    town_index = {str(r["_id"]): r for r in tables["MasterATTownNpc"]}
    for row in tables["MasterATTownNpc"]:
        town_npc_records.append({
            "id": str(row["_id"]),
            "level": _as_number(row.get("_townNpcLv")),
            "defaultAvatar": list(row.get("_defaultAvatar") or []),
            "_source": _source("MasterATTownNpc", row, list(row.keys())),
        })
    for row in tables["MasterATTownNpcArray"]:
        levels = [int(value) for value in (row.get("_townNpcLevelArray") or [])]
        resolved = []
        for level_id in levels:
            level_row = town_index.get(str(level_id))
            if not level_row:
                continue
            resolved.append({
                "id": str(level_row["_id"]),
                "level": _as_number(level_row.get("_townNpcLv")),
            })
        town_pool_records.append({
            "id": str(row["_id"]),
            "size": len(resolved),
            "levels": resolved,
            "_source": _source("MasterATTownNpcArray", row, ("_id", "_townNpcLevelArray")),
        })

    global_params: dict[str, str] = {}
    for row in tables["MasterATGlobal"]:
        key = str(row.get("_id") or "")
        value = str(row.get("_value") or "")
        if key and value:
            global_params[key] = value

    def _g(key: str, default: str = "") -> str:
        return global_params.get(key, default)

    def _gi(key: str, default: int = 0) -> int:
        try:
            return int(float(_g(key, "")))
        except (TypeError, ValueError):
            return default

    def _safe_entry(key: str, label: str, unit: str = "", *, caution: bool = False) -> dict[str, Any]:
        value = _g(key)
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "rawValue": value,
            "unit": unit if unit else None,
        }
        if caution:
            entry["caution"] = True
            entry["cautionNote"] = "该字段仅从原始数据提取，客户端解析语义未验证，不可当成确定攻略。"
        else:
            entry["caution"] = False
        return entry

    sections: list[dict[str, Any]] = []

    sections.append(
        {
            "key": "fever",
            "name": "FEVER 机制",
            "entries": [
                _safe_entry("fever_duration", "FEVER 默认持续时间", "秒"),
                _safe_entry("fever_cd_time", "FEVER 冷却时间", "秒"),
                _safe_entry("fever_game_speed", "FEVER 游戏速度倍率", "倍"),
                _safe_entry("fever_default_shopkeeper_id", "默认 FEVER 店主 ID"),
                _safe_entry("check_out_duration", "FEVER 结账动画持续", "秒"),
                _safe_entry("fever_refresh_interval", "FEVER 客户刷新间隔", "秒", caution=True),
                _safe_entry("fever_drop_interval", "FEVER 掉落间隔", "秒", caution=True),
                _safe_entry("fever_full_drop_time", "FEVER 满掉落时间", "秒", caution=True),
                _safe_entry("fever_customer_spawn_rate", "FEVER 客户生成倍率", caution=True),
                _safe_entry("regular_customer_spawn_rate", "常规客户生成倍率", caution=True),
                _safe_entry("roam_customer_spawn_rate", "自由客户生成倍率", caution=True),
            ],
        }
    )

    sections.append(
        {
            "key": "stamina",
            "name": "体力与恢复",
            "entries": [
                _safe_entry("atstamina_stamina_cap", "体力上限"),
                _safe_entry("stamina_1_recover_value", "初始体力恢复值"),
                _safe_entry("stamina_recover_value", "体力恢复值（单次）"),
                _safe_entry("stamina_recover_seconds", "体力恢复间隔", "秒"),
                _safe_entry("atstamina_restock_stamina_cost", "补货体力消耗"),
                _safe_entry("restork_duration", "补货持续时间", "秒"),
            ],
        }
    )

    sections.append(
        {
            "key": "customers",
            "name": "顾客参数",
            "entries": [
                _safe_entry("bang_customer_base_rate", "乐队顾客基础概率", caution=True),
                _safe_entry("bang_customer_max_rate", "乐队顾客最大概率", caution=True),
                _safe_entry("bang_customer_rate_increament", "乐队顾客概率增量", caution=True),
                _safe_entry("bang_customer_spawn_time", "乐队顾客生成间隔", "秒", caution=True),
                _safe_entry("bang_customer_hard_pity_timer", "保底计时器", "秒", caution=True),
                _safe_entry("bang_customer_offline_threshold", "离线保底阈值", "秒", caution=True),
                _safe_entry("map_customer_min", "地图最少顾客数"),
                _safe_entry("tag_system_double_x", "标签双倍系数 X"),
                _safe_entry("tag_system_one_y", "标签单倍系数 Y"),
                _safe_entry("monologue_click_cooldown_time", "独白点击冷却", "秒", caution=True),
            ],
        }
    )

    sections.append(
        {
            "key": "store",
            "name": "店铺与初始值",
            "entries": [
                _safe_entry("init_coin", "初始金币"),
                _safe_entry("init_anon_badge", "初始 Anon 徽章"),
                _safe_entry("badge_delivery_reduce_sec_per_anon", "徽章配送缩短", "秒/每徽章"),
                _safe_entry("map_shop_default_id", "默认店铺 ID"),
                _safe_entry("map_shop_warehouse", "仓库 ID"),
                _safe_entry("map_shop_default_door", "默认店门 ID"),
            ],
        }
    )

    decoration_kinds: list[dict[str, Any]] = []
    for row in tables["MasterATDecorationSubType"]:
        if not row.get("_isShow"):
            continue
        sub_name = text.resolve(row.get("_nameId"))
        main_type_id = row.get("_type")
        decoration_kinds.append(
            {
                "id": str(row["_id"]),
                "name": sub_name,
                "mainTypeId": str(main_type_id),
                "subType": row.get("_subType"),
                "_source": _source("MasterATDecorationSubType", row, ("_nameId", "_type", "_subType")),
            }
        )
    sections.append(
        {
            "key": "decorationKinds",
            "name": "家具种类",
            "entries": [
                {
                    "key": e["id"],
                    "label": (lambda t: t["values"].get("zh-CN", f"家具分类 {e['id']}"))(text.resolve(e.get("name"))),
                    "rawValue": str(e["mainTypeId"]),
                    "unit": f"主类型 {e['mainTypeId']} 子类型 {e.get('subType')}",
                    "caution": False,
                }
                for e in decoration_kinds
            ],
            "decorationKinds": decoration_kinds,
        }
    )

    staff_effects: list[dict[str, Any]] = []
    for row in tables["MasterATRoleJob"]:
        name = text.resolve(row.get("_namePath"))
        staff_effects.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "iconKey": str(row.get("_iconPath") or ""),
                "_source": _source("MasterATRoleJob", row, ("_namePath", "_iconPath")),
            }
        )
    sections.append(
        {
            "key": "staffEffects",
            "name": "店员岗位效果",
            "entries": [
                {
                    "key": e["id"],
                    "label": (lambda t: t["values"].get("zh-CN", f"店员效果 {e['id']}"))(e["name"] if isinstance(e.get("name"), dict) else text.resolve(e.get("name"))),
                    "rawValue": "",
                    "caution": True,
                    "cautionNote": "具体效果数值在本批版本中尚未从客户端二进制反推，本视图仅展示 Master 中引用的岗位名称。",
                }
                for e in staff_effects
            ],
            "staffEffectDetails": staff_effects,
        }
    )

    all_records: list[dict[str, Any]] = []
    for section in sections:
        for entry in section.get("entries", []):
            all_records.append(section)

    def _name(value: Any) -> str:
        result = text.resolve(value if isinstance(value, Mapping) else None)
        if isinstance(result, dict):
            return result["values"].get("zh-CN") or f"条目 {result.get('key', '')}"
        return str(result)

    sections.append({
        "key": "customers",
        "name": "顾客刷新机制",
        "entries": [
            {
                "key": e["id"],
                "label": f"常驻顾客 L{e['level']}",
                "rawValue": f"停留 {e['minStayDuration']}-{e['maxStayDuration']} 秒",
                "unit": f"基础购买 {e['basePurchaseCount']} 件" + (
                    " · 导购优先" if e["guidedShopping"] else ""
                ),
                "caution": True,
                "cautionNote": "顾客频率与上限受 MasterATGlobal 中 bang_customer_* 参数影响，本表仅展示单个顾客的停留区间与基础购买数。",
            }
            for e in customer_records
        ],
        "customerPools": customer_pool_records,
    })
    sections.append({
        "key": "roamCustomers",
        "name": "流动顾客（自由顾客）",
        "entries": [
            {
                "key": e["id"],
                "label": f"流动顾客 L{e['level']}",
                "rawValue": f"停留 {e['minStayDuration']}-{e['maxStayDuration']} 秒",
                "unit": f"基础购买 {e['basePurchaseCount']} 件",
                "caution": True,
                "cautionNote": "流动顾客的触发与等级池映射由 MasterATRoamCustomerArray 定义；具体时机仍以客户端解析为准。",
            }
            for e in roam_customer_records
        ],
        "roamCustomerPools": roam_pool_records,
    })
    sections.append({
        "key": "townNpcs",
        "name": "城镇 NPC（店外过路）",
        "entries": [
            {
                "key": e["id"],
                "label": f"城镇 NPC L{e['level']}",
                "rawValue": "1 个",
                "unit": f"立绘 {','.join(str(a) for a in e['defaultAvatar'])}",
                "caution": False,
            }
            for e in town_npc_records
        ],
        "townNpcPools": town_pool_records,
    })

    attribute_records: list[dict[str, Any]] = []
    for row in tables["MasterATAttribute"]:
        desc = text.resolve(row.get("_description"))
        level_desc = text.resolve(row.get("_descriptionForLevel"))
        icon_key = str(row.get("_icon") or "")
        default_value = _as_number(row.get("_defaultValue"))
        is_percent = bool(row.get("_isPercent"))
        attribute_records.append({
            "id": str(row["_id"]),
            "label": desc["values"].get("zh-CN", f"属性 {row['_id']}"),
            "levelDescription": level_desc["values"].get("zh-CN", ""),
            "defaultValue": default_value,
            "isPercent": is_percent,
            "iconKey": icon_key or None,
            "rawIcon": icon_key,
            "_source": _source("MasterATAttribute", row, list(row.keys())),
        })
    sections.append({
        "key": "attributes",
        "name": "属性目录",
        "entries": [
            {
                "key": e["id"],
                "label": e["label"],
                "rawValue": f"默认 {e['defaultValue']}{'%' if e['isPercent'] else ''}",
                "unit": f"图标 {e['iconKey'] or '无'}",
                "caution": True,
                "cautionNote": "本表仅整理属性 ID 与图标，客户端公式中具体加成幅度仍需反推。",
            }
            for e in attribute_records
        ],
        "attributes": attribute_records,
    })

    bgm_records: list[dict[str, Any]] = []
    for row in tables["MasterATBgmMusic"]:
        sheet = str(row.get("_cueSheetName") or "")
        cue = str(row.get("_cueName") or "")
        bgm_records.append({
            "id": str(row["_id"]),
            "cueSheetName": sheet,
            "cueName": cue,
            "_source": _source("MasterATBgmMusic", row, list(row.keys())),
        })
    sections.append({
        "key": "bgm",
        "name": "BGM 音乐",
        "entries": [
            {
                "key": e["id"],
                "label": e["cueName"] or f"BGM {e['id']}",
                "rawValue": e["cueSheetName"],
                "unit": None,
                "caution": False,
            }
            for e in bgm_records
        ],
        "bgm": bgm_records,
    })

    init_map_records: list[dict[str, Any]] = []
    for row in tables["MasterATInitMapObjects"]:
        init_map_records.append({
            "id": str(row["_id"]),
            "configId": _as_number(row.get("_configId")),
            "mapIndex": _as_number(row.get("_mapIndex")),
            "tileIndex": _as_number(row.get("_tidx")),
            "direction": _as_number(row.get("_forword")),
            "_source": _source("MasterATInitMapObjects", row, list(row.keys())),
        })
    sections.append({
        "key": "initMap",
        "name": "初始地图对象",
        "entries": [
            {
                "key": e["id"],
                "label": f"地图 {e['mapIndex']} · 配置 {e['configId']}",
                "rawValue": f"瓦片 {e['tileIndex']}",
                "unit": f"方向 {e['direction']}",
                "caution": True,
                "cautionNote": "本表列出首张地图的初始化对象坐标，瓷砖方向含义需结合 MasterATStaticDecoration。",
            }
            for e in init_map_records
        ],
        "initMap": init_map_records,
    })

    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=(
                "MasterATGlobal",
                "MasterATDecorationSubType",
                "MasterATRoleJob",
                "MasterATCustomer",
                "MasterATCustomerArray",
                "MasterATRoamCustomer",
                "MasterATRoamCustomerArray",
                "MasterATTownNpc",
                "MasterATTownNpcArray",
                "MasterATAttribute",
                "MasterATBgmMusic",
                "MasterATInitMapObjects",
            ),
            records=[],
            sections=sections,
        ),
        set(),
    )


def _build_themes(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    decorations = {str(row["_id"]): row for row in tables["MasterATDecoration"]}
    media: set[str] = set()
    records: list[dict[str, Any]] = []
    for row in tables.get("MasterATSuitTheme", []):
        warnings: list[str] = []
        required_ids: list[str] = []
        unlocked_ids: list[str] = []
        for raw_id in row.get("_needCollect") or []:
            identity, relation_warnings = _ref_status(
                raw_id, decorations, "theme_required_decoration"
            )
            if identity:
                required_ids.append(identity)
            warnings.extend(relation_warnings)
        for raw_id in row.get("_rewardCanBuyId") or []:
            identity, relation_warnings = _ref_status(
                raw_id, decorations, "theme_unlocked_decoration"
            )
            if identity:
                unlocked_ids.append(identity)
            warnings.extend(relation_warnings)
        name = text.resolve(row.get("_suitName"))
        preview_key = str(row.get("_promoImagePath") or "")
        if preview_key:
            media.add(preview_key)
        records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "requiredDecorationIds": required_ids,
                "unlockedDecorationIds": unlocked_ids,
                "previewKey": preview_key or None,
                "reward": _parse_reward(row.get("_reward")),
                "availabilityConfig": {
                    "start": row.get("_startTime"),
                    "end": row.get("_endTime"),
                },
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings, names=[name]),
                **_source("MasterATSuitTheme", row, row.keys()),
            }
        )
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterATSuitTheme", "MasterATDecoration"),
            records=sorted(records, key=lambda item: item["id"]),
        ),
        media,
    )


def _parse_relation_pairs(value: Any, *, label: str) -> list[tuple[str, str]]:
    if value in (None, ""):
        return []
    result = []
    for group in str(value).split(";"):
        parts = [part.strip() for part in group.split(",")]
        if len(parts) != 2 or not all(parts):
            raise AnonTokyoProjectionError(f"{label} contains an invalid relation pair")
        result.append((parts[0], parts[1]))
    return result


def _build_stages(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    bands = {str(row["_id"]): row for row in tables["MasterBand"]}
    characters = {str(row["_id"]): row for row in tables["MasterATCharacter"]}
    buffs = {str(row["_id"]): row for row in tables["MasterATStageBuff"]}
    music_by_band: dict[str, list[dict[str, Any]]] = {}
    media: set[str] = set()
    for row in tables["MasterATStageMusic"]:
        music_by_band.setdefault(str(row.get("_bandID")), []).append(row)

    buff_records = []
    for row in buffs.values():
        name = text.resolve(row.get("_buffName"))
        icon = str(row.get("_icon") or "")
        if icon:
            media.add(icon)
        buff_records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "iconKey": icon or None,
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATStageBuff", row, row.keys()),
            }
        )

    records = []
    for row in tables["MasterATStage"]:
        warnings: list[str] = []
        band_id, band_warnings = _ref_status(row.get("_bandID"), bands, "stage_band")
        warnings.extend(band_warnings)
        band = bands.get(band_id or "")
        band_name = text.resolve(band.get("_nameTextID")) if band else text.resolve(None)
        member_ids = []
        for raw_id in row.get("_feverBandMembers") or []:
            member_id, member_warnings = _ref_status(
                raw_id, characters, "stage_member"
            )
            if member_id:
                member_ids.append(member_id)
            warnings.extend(member_warnings)

        music_rows = sorted(
            music_by_band.get(band_id or "", []),
            key=lambda value: (not bool(value.get("_stageDefaultMusic")), str(value["_id"])),
        )
        music = None
        if music_rows:
            music_row = music_rows[0]
            icon = str(music_row.get("_iconPathName") or "")
            if icon:
                media.add(icon)
            music = {
                "id": str(music_row["_id"]),
                "name": text.resolve(music_row.get("_name")),
                "duration": music_row.get("_musicTime"),
                "defaultUnlocked": bool(music_row.get("_defaultUnlockState")),
                "levelLimit": music_row.get("_levelLimit"),
                "purchase": {
                    "itemId": music_row.get("_buyItemId"),
                    "itemCount": music_row.get("_buyItemCount"),
                },
                "iconKey": icon or None,
            }
        else:
            warnings.append(f"unresolved_stage_music:{band_id}")

        effects = []
        for buff_id, raw_value in _parse_relation_pairs(
            row.get("_feverBufferReward"), label="MasterATStage fever buffer"
        ):
            buff = next((item for item in buff_records if item["id"] == buff_id), None)
            if not buff:
                warnings.append(f"unresolved_stage_buff:{buff_id}")
                continue
            effects.append(
                {
                    "buffId": buff_id,
                    "name": buff["name"],
                    "iconKey": buff.get("iconKey"),
                    "rawValue": raw_value,
                }
            )
        records.append(
            {
                "id": str(row["_id"]),
                "bandId": band_id,
                "bandName": band_name,
                "memberIds": member_ids,
                "music": music,
                "feverEffects": effects,
                "availabilityConfig": {
                    "start": row.get("_startAt"),
                    "end": row.get("_endAt"),
                },
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings, names=[band_name]),
                **_source("MasterATStage", row, row.keys()),
            }
        )
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterBand", "MasterATStage", "MasterATStageBuff", "MasterATStageMusic"),
            records=sorted(records, key=lambda item: item["id"]),
            buffs=sorted(buff_records, key=lambda item: item["id"]),
        ),
        media,
    )


def _build_chats(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    characters = {str(row["_id"]): row for row in tables["MasterATCharacter"]}
    chat_managers = {
        str(row["_id"]): row for row in tables["MasterATCharChatManage"]
    }
    scene_fields = (
        ("cashier", "_cashier"),
        ("sales", "_guider"),
        ("restocking", "_replenishmentStaff"),
    )
    records = []
    for row in tables["MasterATCharChat"]:
        warnings: list[str] = []
        raw_character_ids = str(row["_id"]).split("_")
        character_ids = []
        if len(raw_character_ids) != 2:
            warnings.append(f"invalid_chat_pair:{row['_id']}")
        else:
            for raw_id in raw_character_ids:
                identity, relation_warnings = _ref_status(
                    raw_id, characters, "chat_character"
                )
                if identity:
                    character_ids.append(identity)
                warnings.extend(relation_warnings)
        scenes = []
        for kind, field in scene_fields:
            manager_id = str(row.get(field))
            manager = chat_managers.get(manager_id)
            if not manager:
                warnings.append(f"unresolved_chat_manager:{manager_id}")
                continue
            raw_keys = manager.get("_chatWordsIds")
            keys = [value.strip() for value in str(raw_keys or "").split(",") if value.strip()]
            lines = [text.resolve(key) for key in keys]
            if not lines:
                warnings.append(f"empty_chat_manager:{manager_id}")
                continue
            scenes.append({"kind": kind, "managerId": manager_id, "lines": lines})
        speaker_resolution: dict[str, str] = {}
        if len(character_ids) == 2:
            first, second = character_ids
            manager_to_kind = {
                str(row.get(field)): kind for kind, field in scene_fields
            }
            for scene in scenes:
                speaker_resolution[scene["kind"]] = first
                speaker_resolution[f"{scene['kind']}_secondary"] = second
        records.append(
            {
                "id": str(row["_id"]),
                "characterIds": character_ids,
                "scenes": scenes,
                "speakerMapping": "ambiguous" if len(character_ids) == 2 else "unresolved",
                "speakerMappingVerified": False,
                "speakerResolution": speaker_resolution,
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings),
                **_source("MasterATCharChat", row, row.keys()),
            }
        )

    monologue_texts = {
        str(row["_id"]): row for row in tables["MasterATMonologueMain"]
    }
    role_fields = (
        ("cashier", "_monologueCashier"),
        ("sales", "_monologueShopAss"),
        ("restocking", "_monologueRestocker"),
        ("standby", "_monologueStandby"),
    )
    monologues = []
    for row in tables["MasterATMonologueChar"]:
        warnings: list[str] = []
        character_id, character_warnings = _ref_status(
            row.get("_id"), characters, "monologue_character"
        )
        warnings.extend(character_warnings)
        roles = []
        for kind, field in role_fields:
            monologue_id = str(row.get(field))
            definition = monologue_texts.get(monologue_id)
            if not definition:
                warnings.append(f"unresolved_monologue:{monologue_id}")
                roles.append({"kind": kind, "text": None})
                continue
            roles.append(
                {
                    "kind": kind,
                    "text": text.resolve(definition.get("_monologueText")),
                }
            )
        monologues.append(
            {
                "characterId": character_id,
                "roles": roles,
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings),
                **_source("MasterATMonologueChar", row, row.keys()),
            }
        )
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=(
                "MasterATCharChat",
                "MasterATCharChatManage",
                "MasterATMonologueChar",
                "MasterATMonologueMain",
            ),
            records=sorted(records, key=lambda item: item["id"]),
            monologues=sorted(monologues, key=lambda item: str(item["characterId"])),
        ),
        set(),
    )


def _build_tasks(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    types = {str(row["_id"]): row for row in tables["MasterATTaskType"]}
    predecessors = {
        str(row["_id"]): str(row.get("_beforeTaskID"))
        for row in tables.get("MasterATAchievementTask", [])
        if row.get("_beforeTaskID") not in (None, 0, "0")
    }
    media: set[str] = set()
    reward_items = []
    for row in tables.get("MasterATCurrencyType", []):
        name = text.resolve(row.get("_suitName"))
        icon = str(row.get("_icon") or "")
        if icon:
            media.add(icon)
        reward_items.append(
            {
                "id": str(row["_id"]),
                "rewardType": "1",
                "name": name,
                "iconKey": icon or None,
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATCurrencyType", row, row.keys()),
            }
        )
    type_records = []
    for row in types.values():
        description = text.resolve(row.get("_description"))
        icon = str(row.get("_icon") or "")
        if icon:
            media.add(icon)
        type_records.append(
            {
                "id": str(row["_id"]),
                "description": description,
                "parameters": [row.get("_param1") or None, row.get("_param2") or None, row.get("_param3") or None],
                "iconKey": icon or None,
                "jumpTabType": row.get("_jumpTabType"),
                "interpretationStatus": _status(warnings=[], names=[description]),
                **_source("MasterATTaskType", row, row.keys()),
            }
        )
    records = []
    for row in tables["MasterATTaskMain"]:
        warnings: list[str] = []
        type_id, type_warnings = _ref_status(row.get("_taskTypeID"), types, "task_type")
        warnings.extend(type_warnings)
        task_type = types.get(type_id or "", {})
        parameter_names = [task_type.get("_param1"), task_type.get("_param2"), task_type.get("_param3")]
        parameters = []
        for index, name in enumerate(parameter_names, start=1):
            value = row.get(f"_param{index}")
            if name:
                parameters.append({"name": str(name), "value": value})
            elif value not in (None, 0, "", "0"):
                warnings.append(f"uninterpreted_param{index}")
                parameters.append({"name": None, "value": value})
        records.append(
            {
                "id": str(row["_id"]),
                "taskTypeId": type_id,
                "taskTabId": str(row.get("_taskTabsID")) if row.get("_taskTabsID") is not None else None,
                "parameters": parameters,
                "reward": _parse_reward(row.get("_reward")),
                "rewardRaw": row.get("_reward"),
                "predecessorTaskId": predecessors.get(str(row["_id"])),
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings),
                **_source("MasterATTaskMain", row, row.keys()),
            }
        )
    reward_index: dict[str, list[str]] = {}
    for record in records:
        for reward in record["reward"]:
            key = f"{reward['type']}:{reward['itemId']}"
            reward_index.setdefault(key, []).append(record["id"])
    extra_groups = {
        "tabs": "MasterATTaskTabs",
        "chapters": "MasterATChapterTask",
        "dailyDefinitions": "MasterATDailyTask",
        "achievements": "MasterATAchievement",
        "achievementLinks": "MasterATAchievementTask",
        "rewardTypes": "MasterATReward",
        "suits": "MasterATSuitTheme",
    }
    extras = {
        key: _simple_records(table, tables.get(table, []), text)
        for key, table in extra_groups.items()
    }

    structured_chapters = []
    for row in tables.get("MasterATChapterTask", []):
        ch_name = text.resolve(row.get("_chapterName"))
        task_ids = [str(tid) for tid in (row.get("_taskIDList") or [])]
        structured_chapters.append(
            {
                "id": str(row["_id"]),
                "name": ch_name,
                "taskIds": task_ids,
                "reward": _parse_reward(row.get("_reward")),
                "taskCount": len(task_ids),
            }
        )
    structured_chapters.sort(key=lambda item: item["id"])

    achievement_links_raw = tables.get("MasterATAchievementTask", [])
    link_index: dict[str, dict[str, Any]] = {
        str(item["_id"]): item for item in achievement_links_raw
    }
    children_of: dict[str, list[str]] = {}
    for item in achievement_links_raw:
        task_id = str(item["_id"])
        before = str(item.get("_beforeTaskID", 0))
        children_of.setdefault(before, []).append(task_id)
    chains: list[list[str]] = []
    roots = [str(item["_id"]) for item in achievement_links_raw if item.get("_beforeTaskID") in (None, 0, "0")]
    for root_id in roots:
        chain: list[str] = []
        current = root_id
        while current:
            chain.append(current)
            children = children_of.get(current, [])
            current = children[0] if children else None
        chains.append(chain)

    structured_chains: list[dict[str, Any]] = []
    for chain in chains:
        if not chain:
            continue
        head = chain[0]
        first_link = link_index.get(head, {})
        first_task_name = str(first_link.get("_taskName", ""))
        chain_name = text.resolve(first_task_name) if first_task_name else None
        structured_chains.append(
            {
                "name": chain_name,
                "taskIds": chain,
                "firstTaskId": head,
                "lastTaskId": chain[-1],
                "length": len(chain),
            }
        )
    structured_chains.sort(key=lambda item: item["firstTaskId"])

    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=("MasterATTaskMain", "MasterATTaskType", *extra_groups.values()),
            records=sorted(records, key=lambda item: item["id"]),
            taskTypes=sorted(type_records, key=lambda item: item["id"]),
            rewardIndex={key: sorted(value) for key, value in sorted(reward_index.items())},
            rewardItems=sorted(reward_items, key=lambda item: item["id"]),
            structuredChapters=structured_chapters,
            structuredAchievementChains=structured_chains,
            **extras,
        ),
        media,
    )


def _parse_abilities(value: Any) -> list[dict[str, int]]:
    if value in (None, ""):
        return []
    result = []
    for group in str(value).split(";"):
        parts = group.split(",")
        if len(parts) != 2:
            raise AnonTokyoProjectionError("MasterATCharacter contains an invalid passive ability list")
        try:
            result.append({"abilityId": int(parts[0]), "value": int(parts[1])})
        except ValueError as exc:
            raise AnonTokyoProjectionError(
                "MasterATCharacter contains an invalid passive ability list"
            ) from exc
    return result


def _build_staff(
    tables: Mapping[str, list[dict[str, Any]]], text: _TextIndex
) -> tuple[dict[str, Any], set[str]]:
    abilities = {str(row["_id"]): row for row in tables["MasterATCharPassiveAbility"]}
    avatars = {
        str(row["_id"]): str(row.get("_avatarPath") or "")
        for row in tables["MasterATAvatar"]
    }
    media: set[str] = set()
    ability_records = []
    for row in abilities.values():
        name = text.resolve(row.get("_passiveAbilityName"))
        icon = str(row.get("_icon") or "")
        if icon:
            media.add(icon)
        ability_records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "value": text.resolve(row.get("_passiveAbilityValue")),
                "iconKey": icon or None,
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATCharPassiveAbility", row, row.keys()),
            }
        )
    role_records = []
    for row in tables["MasterATRoleJob"]:
        name = text.resolve(row.get("_namePath"))
        icon = str(row.get("_iconPath") or "")
        if icon:
            media.add(icon)
        role_records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "iconKey": icon or None,
                "interpretationStatus": _status(warnings=[], names=[name]),
                **_source("MasterATRoleJob", row, row.keys()),
            }
        )
    records = []
    for row in tables["MasterATCharacter"]:
        warnings: list[str] = []
        image_key = avatars.get(str(row.get("_avatarID")), "")
        if image_key:
            media.add(image_key)
        else:
            warnings.append(f"unresolved_avatar:{row.get('_avatarID')}")
        ability_values = _parse_abilities(row.get("_charPassiveAbility"))
        for ability in ability_values:
            if str(ability["abilityId"]) not in abilities:
                warnings.append(f"unresolved_ability:{ability['abilityId']}")
        name = text.resolve(row.get("_name"))
        records.append(
            {
                "id": str(row["_id"]),
                "name": name,
                "imageKey": image_key or None,
                "identityNumber": row.get("_bangIdentityNumber"),
                "levelLimit": row.get("_levelLimit"),
                "unlock": {
                    "itemId": row.get("_buyItemId"),
                    "itemCount": row.get("_buyItemCount"),
                    "initType": row.get("_initType"),
                },
                "passiveAbilities": ability_values,
                "passiveAbilitiesRaw": row.get("_charPassiveAbility"),
                "clientSemanticsVerified": False,
                "warnings": sorted(set(warnings)),
                "interpretationStatus": _status(warnings=warnings, names=[name]),
                **_source("MasterATCharacter", row, row.keys()),
            }
        )
    clerks = _simple_records("MasterATClerk", tables.get("MasterATClerk", []), text)
    try:
        assignment_studio = build_staff_assignment_evidence(
            roles=tables["MasterATRoleJob"],
            attributes=tables["MasterATAttribute"],
            player_levels=tables.get("MasterATPlayer", []),
        )
    except ValueError as exc:
        raise AnonTokyoProjectionError(str(exc)) from exc
    return (
        _base_document(
            release_id="",
            generated_at="",
            tables=(
                "MasterATCharacter",
                "MasterATAvatar",
                "MasterATCharPassiveAbility",
                "MasterATRoleJob",
                "MasterATClerk",
            ),
            records=sorted(records, key=lambda item: item["id"]),
            passiveAbilities=sorted(ability_records, key=lambda item: item["id"]),
            roles=sorted(role_records, key=lambda item: item["id"]),
            clerks=clerks,
            assignmentStudio=assignment_studio,
        ),
        media,
    )


def _media_document(
    *,
    release_id: str,
    generated_at: str,
    media_keys: Iterable[str],
    catalog_path: Path,
) -> tuple[dict[str, Any], str]:
    try:
        snapshot = CatalogAdapter().parse(catalog_path)
    except Exception as exc:
        raise AnonTokyoProjectionError("Catalog is unreadable or unsupported") from exc
    selectors = {
        selector
        for location in snapshot.locations
        for selector in (location.primary_key, *location.keys, *location.labels)
    }
    records = [
        {
            "id": (media_id := hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]),
            "logicalKey": key,
            "availableInCatalog": key in selectors,
            "usage": "entity_preview",
            "previewUrl": f"/media/anontokyo/{media_id}.png",
            "interpretationStatus": "verified" if key in selectors else "partial",
        }
        for key in sorted(set(media_keys))
        if key
    ]
    return (
        _base_document(
            release_id=release_id,
            generated_at=generated_at,
            tables=(),
            records=records,
            catalogHash=snapshot.catalog_hash,
        ),
        snapshot.catalog_hash,
    )


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _validate_generated_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        raise AnonTokyoProjectionError("generated_at must be an ISO-8601 UTC timestamp")
    return value


def build_anontokyo_projection(
    *,
    master_root: Path,
    catalog_path: Path,
    map_config_path: Path | None = None,
    output_root: Path,
    source_release_id: str,
    generated_at: str | None = None,
) -> AnonTokyoProjectionResult:
    """Build all private guide datasets behind one stable interface."""
    if not RELEASE_ID_PATTERN.fullmatch(source_release_id):
        raise AnonTokyoProjectionError("source_release_id must be a path-safe lowercase identifier")
    timestamp = _validate_generated_at(generated_at)
    if output_root.exists():
        raise AnonTokyoProjectionError("projection output already exists")

    tables = {
        name: _load_table(master_root, name, required=True)
        for name in REQUIRED_TABLES
    }
    tables.update(
        {
            name: _load_table(master_root, name, required=False)
            for name in OPTIONAL_TABLES
        }
    )
    text = _TextIndex(tables["MasterText"])

    goods, goods_media = _build_goods(tables, text)
    decorations, decoration_media = _build_decorations(tables, text)
    progression, progression_media = _build_progression(tables, text)
    tasks, task_media = _build_tasks(tables, text)
    themes, theme_media = _build_themes(tables, text)
    stages, stage_media = _build_stages(tables, text)
    chats, chat_media = _build_chats(tables, text)
    staff, staff_media = _build_staff(tables, text)
    wardrobe, wardrobe_media = _build_wardrobe(tables, text)
    inspiration, inspiration_media = _build_inspiration(tables, text)
    guide, guide_media = _build_guide(tables, text)
    mechanics, mechanics_media = _build_mechanics(tables, text)
    documents = {
        "goods.json": goods,
        "decorations.json": decorations,
        "themes.json": themes,
        "stages.json": stages,
        "chats.json": chats,
        "wardrobe.json": wardrobe,
        "inspiration.json": inspiration,
        "progression.json": progression,
        "tasks.json": tasks,
        "staff.json": staff,
        "guide.json": guide,
        "mechanics.json": mechanics,
    }
    if map_config_path is not None:
        try:
            documents["map.json"] = build_studio_map_document(
                map_config_path,
                static_decoration_rows=tables["MasterATStaticDecoration"],
            )
        except AnonTokyoStudioError as exc:
            raise AnonTokyoProjectionError(str(exc)) from exc
    for document in documents.values():
        document["sourceReleaseId"] = source_release_id
        document["generatedAt"] = timestamp
    map_media = set(documents.get("map.json", {}).get("mediaKeys", []))
    media_document, catalog_hash = _media_document(
        release_id=source_release_id,
        generated_at=timestamp,
        media_keys=(
            goods_media
            | decoration_media
            | progression_media
            | task_media
            | theme_media
            | stage_media
            | chat_media
            | staff_media
            | wardrobe_media
            | inspiration_media
            | guide_media
            | mechanics_media
            | map_media
        ),
        catalog_path=catalog_path,
    )
    documents["media-manifest.json"] = media_document

    parent = output_root.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.partial-", dir=parent))
    except OSError as exc:
        raise AnonTokyoProjectionError("projection output cannot be prepared") from exc
    try:
        files: dict[str, dict[str, Any]] = {}
        output_files = (*OUTPUT_FILES, *(("map.json",) if "map.json" in documents else ()))
        for name in output_files:
            data = _json_bytes(documents[name])
            (stage / name).write_bytes(data)
            files[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        all_records = [
            record
            for name in output_files
            for record in documents[name].get("records", [])
        ]
        map_tile_count = 0
        if "map.json" in documents:
            grid = documents["map.json"]["map"]["grid"]
            map_tile_count = grid["width"] * grid["height"]
        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "sourceReleaseId": source_release_id,
            "generatedAt": timestamp,
            "inputSummary": {
                "catalogHash": catalog_hash,
                **(
                    {"mapConfigHash": documents["map.json"]["sourceHash"]}
                    if "map.json" in documents
                    else {}
                ),
                "masterTables": {
                    name: _table_sha256(master_root, name)
                    for name in sorted(tables)
                    if (master_root / f"{name}.json").is_file()
                },
            },
            "recordCounts": {
                "goods": len(goods["records"]),
                "decorations": len(decorations["records"]),
                "themes": len(themes["records"]),
                "stages": len(stages["records"]),
                "chatCombinations": len(chats["records"]),
                "monologueCharacters": len(chats["monologues"]),
                "wardrobe": len(wardrobe["records"]),
                "wardrobeWithVerifiedCharacters": sum(
                    1
                    for record in wardrobe["records"]
                    if isinstance(record, dict)
                    and record.get("characterAttributionVerified")
                ),
                "inspirationTiers": len(inspiration["records"]),
                "storeLevels": len(progression["storeLevels"]),
                "tasks": len(tasks["records"]),
                "taskTypes": len(tasks["taskTypes"]),
                "characters": len(staff["records"]),
                "guideSteps": len(guide["records"]),
                "guideChapters": len(guide["chapters"]),
                "mechanicsSections": len(mechanics["sections"]),
                "taskChapters": len(tasks.get("structuredChapters", [])),
                "taskAchievementChains": len(tasks.get("structuredAchievementChains", [])),
                "mediaCandidates": len(media_document["records"]),
                "mapTiles": map_tile_count,
            },
            "qualitySummary": _quality(all_records),
            "formulaCapabilities": dict(FORMULA_CAPABILITIES),
            "files": files,
        }
        (stage / "manifest.json").write_bytes(_json_bytes(manifest))
        os.replace(stage, output_root)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, AnonTokyoProjectionError):
            raise
        raise AnonTokyoProjectionError("projection output cannot be written") from exc

    return AnonTokyoProjectionResult(
        output_root=output_root,
        manifest=manifest,
        files=tuple(output_root / name for name in ("manifest.json", *output_files)),
    )
