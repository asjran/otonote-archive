"""Resolve item outputs and score-rank-specific live reward configuration."""
from collections import defaultdict
from pathlib import Path

from tools.system_details import SystemContext


def build_live_item_drops(master_root: Path) -> dict:
    """Keep each reward roll separate, including its unallocated no-drop chance.

    The live tables use a 10,000-point probability scale: guaranteed currency
    rows have 10,000 and the five color alternatives have 2,000 each. Rare-item
    groups deliberately total less than 10,000; normalizing by their group sum
    would incorrectly turn a 30-point (0.3%) drop into a guaranteed reward.
    These are base configuration rates, not simulated boosted settlement odds.
    """
    ctx = SystemContext(master_root, "zh-CN")
    result = defaultdict(list)
    for table, mode in (("MasterLiveFreeReward", "solo"), ("MasterBattleLiveReward", "multi")):
        for row in ctx.rows(table):
            if row.get("_resourceType") != 1 or row.get("_resourceCount", 0) <= 0:
                continue
            probability = row.get("_probability")
            if isinstance(probability, bool) or not isinstance(probability, int) or not 0 <= probability <= 10000:
                raise ValueError(f"Invalid live drop probability in {table}: {row.get('_id')}")
            rank = row.get("_liveScoreRank")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank not in range(1, 8):
                raise ValueError(f"Invalid live score rank in {table}: {row.get('_id')}")
            if probability == 0:
                continue
            result[f"item-{row['_resourceId']}"].append({
                "mode": mode,
                "scoreRank": rank,
                "rewardGroup": row["_group"],
                "count": row["_resourceCount"],
                "probability": probability,
                "probabilityBase": 10000,
            })
    return {key: sorted(rows, key=lambda row: (row["mode"], -row["scoreRank"], row["rewardGroup"]))
            for key, rows in result.items()}


def build_item_acquisition(master_root: Path, locale: str = "zh-CN") -> dict:
    ctx = SystemContext(master_root, locale)
    result = defaultdict(list)
    for table, parent_table, foreign_key, kind in (
        ("MasterShopProduct", "MasterShop", "_shopId", "shop"),
        ("MasterExchangeProduct", "MasterExchange", "_exchangeId", "exchange"),
    ):
        parents = {row["_id"]: row for row in ctx.rows(parent_table)}
        for row in ctx.rows(table):
            if row.get("_resourceType") != 1 or row.get("_resourceCount", 0) <= 0:
                continue
            parent = parents.get(row.get(foreign_key))
            if not parent:
                continue
            # Both windows apply. Keep configured dates without inferring a timezone.
            windows = [
                {"startAt": value.get("_startAt") or "", "endAt": value.get("_endAt") or ""}
                for value in (parent, row) if value.get("_startAt") or value.get("_endAt")
            ]
            result[f"item-{row['_resourceId']}"].append({
                "kind": kind,
                "name": ctx.text(parent.get("_nameTextId"), "商店" if kind == "shop" else "交换所"),
                "count": row["_resourceCount"],
                "windows": windows,
                "isBonus": bool(row.get("_isBonus")),
            })
    return dict(result)
