"""Project Global production gacha, T.G.W CARD and Studio Practice data.

The projection describes versioned Master configuration. It never infers a
live server opening state or a player's purchase/progression state.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.resource_pipeline.localization import resolve_localized_text
from tools.system_details import enrich_systems


class GlobalSystemsError(ValueError):
    pass


def _rows(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise GlobalSystemsError(f"missing Master table: {name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise GlobalSystemsError(f"invalid Master table: {name}")
    return rows


def empty_global_systems(release_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "status": "unavailable_outside_global_production",
        "gachaPools": [],
        "missions": [],
        "vipRanks": [],
        "studioUnits": [],
        "evidence": [],
    }


def build_global_systems(root: Path, release_id: str, locale: str) -> dict[str, Any]:
    names = (
        "MasterText", "MasterGacha", "MasterGachaLot", "MasterGachaPrize",
        "MasterGachaProduct", "MasterMemberCard", "MasterSupportCard", "MasterVip",
        "MasterVipRankBonus", "MasterVipDailyPoint", "MasterVipDailyReward",
        "MasterVipRankUpReward", "MasterOfflineBonusUnit",
        "MasterOfflineBonusUnitLevel", "MasterOfflineBonusExpFactor",
        "MasterOfflineBonusItemLot",
    )
    tables = {name: _rows(root, name) for name in names}
    texts = {row.get("_id"): row for row in tables["MasterText"]}

    def label(text_id: str, fallback: str) -> str:
        return resolve_localized_text(texts.get(text_id), locale, fallback).text

    cards = {row["_id"] for row in tables["MasterMemberCard"]}
    supports = {row["_id"] for row in tables["MasterSupportCard"]}
    lots: dict[int, set[int]] = defaultdict(set)
    for row in tables["MasterGachaLot"]:
        lots[row["_lotGroupId"]].add(row["_prizeGroupId"])
    prizes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["MasterGachaPrize"]:
        prizes[row["_groupId"]].append(row)
    products = {row["_id"]: row for row in tables["MasterGachaProduct"]}
    gacha_pools = []
    for row in sorted(tables["MasterGacha"], key=lambda item: (-item["_priority"], item["_id"])):
        group_ids = sorted(lots[row["_lotGroupId"]])
        pickups = sorted({
            prize["_resourceId"]
            for group_id in group_ids
            for prize in prizes[group_id]
            if prize.get("_pickUpType") == 2
            and prize.get("_resourceType") == 2
            and prize.get("_resourceId") in cards
        })
        pickup_supports = sorted({
            prize["_resourceId"]
            for group_id in group_ids
            for prize in prizes[group_id]
            if prize.get("_pickUpType") == 2
            and prize.get("_resourceType") == 3
            and prize.get("_resourceId") in supports
        })
        product_ids = [row.get(f"_productId{index}") for index in range(1, 5)]
        product_ids = list(dict.fromkeys(value for value in product_ids if value))
        if any(value not in products for value in product_ids):
            raise GlobalSystemsError(f"gacha {row['_id']} references a missing product")
        gacha_pools.append({
            "id": row["_id"],
            "name": label(row["_nameTextId"], f"Gacha #{row['_id']}"),
            "startAt": row.get("_startAt") or None,
            "endAt": row.get("_endAt") or None,
            "isLimited": bool(row.get("_isLimited")),
            "bannerAssetName": row.get("_bannerAssetName") or None,
            "lotGroupId": row["_lotGroupId"],
            "prizeGroupIds": group_ids,
            "pickupMemberCardIds": pickups,
            "pickupSupportCardIds": pickup_supports,
            "supportCardIds": sorted({prize["_resourceId"] for group_id in group_ids
                                      for prize in prizes[group_id]
                                      if prize.get("_resourceType") == 3
                                      and prize.get("_resourceId") in supports}),
            "products": [{
                "id": value,
                "drawCount": products[value]["_drawCount"],
                "price": products[value]["_price"],
                "itemType": products[value]["_itemType"],
            } for value in product_ids],
            "relatedEventIds": [],
            "eventRelationStatus": "no_explicit_relation_in_snapshot",
        })

    bonus_by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["MasterVipRankBonus"]:
        bonus_by_rank[row["_vipRank"]].append({
            "type": row["_vipBonusType"],
            "label": label(f"ui_vip_bonus_type_{row['_vipBonusType']}", f"Type {row['_vipBonusType']}"),
            "rawValue": row["_value"],
        })
    reward_by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["MasterVipRankUpReward"]:
        reward_by_rank[row["_vipRank"]].append({
            "resourceType": row["_resourceType"],
            "resourceId": row["_resourceId"],
            "count": row["_resourceCount"],
        })
    daily_by_rank: dict[int, int] = defaultdict(int)
    for row in tables["MasterVipDailyReward"]:
        daily_by_rank[row["_vipRank"]] += 1
    vip_ranks = [{
        "rank": row["_vipRank"],
        "requiredPoints": row["_point"],
        "bonuses": sorted(bonus_by_rank[row["_vipRank"]], key=lambda item: item["type"]),
        "rankUpRewards": reward_by_rank[row["_vipRank"]],
        "dailyRewardRows": daily_by_rank[row["_vipRank"]],
    } for row in sorted(tables["MasterVip"], key=lambda item: item["_vipRank"])]

    levels: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["MasterOfflineBonusUnitLevel"]:
        levels[row["_offlineBonusUnitId"]].append({
            "level": row["_offlineBonusLevel"],
            "requiredExp": row["_offlineBonusExp"],
            "unlockBandRank": row["_unlockBandRank"],
            "efficiencySeconds": row["_offlineEfficiencyTime"],
            "limitSeconds": row["_offlineLimitTime"],
            "rawEarnCoin": row["_earnCoin"],
            "rawEarnMemberExp": row["_earnMemberExp"],
            "rawEarnSupportExp": row["_earnSupportExp"],
            "rawEarnOfflineBonusExp": row["_earnOfflineBonusExp"],
            "itemLotGroupId": row["_itemLotGroupId"],
        })
    studio_units = [{
        "id": row["_id"],
        "name": row["_name"],
        "bandId": row["_bandId"],
        "startAt": row.get("_startAt") or None,
        "levels": sorted(levels[row["_id"]], key=lambda item: item["level"]),
    } for row in sorted(tables["MasterOfflineBonusUnit"], key=lambda item: item["_id"])]
    if any(not unit["levels"] for unit in studio_units):
        raise GlobalSystemsError("studio unit has no level configuration")
    return enrich_systems({
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "status": "configured_snapshot",
        "gachaPools": gacha_pools,
        "vipRanks": vip_ranks,
        "vipDailyPoints": [{
            "consecutiveDays": row["_consecutiveCount"], "points": row["_point"]
        } for row in sorted(tables["MasterVipDailyPoint"], key=lambda item: item["_consecutiveCount"])],
        "studioUnits": studio_units,
        "evidence": [{"table": name, "rowCount": len(tables[name])} for name in names],
    }, root, locale)
