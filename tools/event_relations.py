"""Event links use explicit IDs, or corroborated card/period/name evidence.

Never link a recruitment pool or pass solely because its dates overlap.
"""
import re
from tools.system_details import enrich_systems


def normalized(value):
    return re.sub(r"\s+", "", str(value or "").replace("\\u3000", " "))


def build_event_relations(source, event, effects):
    def rows(name):
        return source.rows(name) if (source.root / f"{name}.json").is_file() else []

    def title(table, row):
        return source.name(table, row["_id"]).replace("\\u3000", " ")

    event_id = event["_id"]
    featured = {(kind, effect["constraints"].get(key)) for effect in effects
                for kind, key in ((2, "memberCardId"), (3, "supportCardId"))
                if effect["constraints"].get(key)}
    lots, prizes = rows("MasterGachaLot"), rows("MasterGachaPrize")
    products = {row["_id"]: row for row in rows("MasterGachaProduct")}
    pools = []
    for pool in rows("MasterGacha"):
        groups = {row["_prizeGroupId"] for row in lots if row["_lotGroupId"] == pool.get("_lotGroupId")}
        pickups = {(r.get("_resourceType"), r.get("_resourceId")) for r in prizes
                   if r.get("_groupId") in groups and r.get("_pickUpType") == 2}
        explicit = pool.get("_eventId") == event_id
        matched = (not pool.get("_eventId") and pool.get("_warningTextId") == "gacha_warning_event"
                   and pool.get("_startAt") == event.get("_startAt") and bool(pickups & featured))
        if not explicit and not matched:
            continue
        product_ids = list(dict.fromkeys(pool.get(f"_productId{i}") for i in range(1, 5)))
        pools.append({"id": pool["_id"], "name": title("MasterGacha", pool),
                      "startAt": pool.get("_startAt"), "endAt": pool.get("_endAt"),
                      "isLimited": bool(pool.get("_isLimited")), "bannerAssetName": pool.get("_bannerAssetName"),
                      "lotGroupId": pool.get("_lotGroupId"), "prizeGroupIds": sorted(groups),
                      "pickupMemberCardIds": sorted(i for kind, i in pickups if kind == 2),
                      "pickupSupportCardIds": sorted(i for kind, i in pickups if kind == 3),
                      "supportCardIds": sorted({r["_resourceId"] for r in prizes if r.get("_groupId") in groups and r.get("_resourceType") == 3}),
                      "products": [{"id": i, "drawCount": products[i]["_drawCount"], "price": products[i]["_price"],
                                    "itemType": products[i]["_itemType"]} for i in product_ids if i in products],
                      "relatedEventIds": [event_id], "eventRelationStatus": "explicit_id" if explicit else "featured_cards_and_start",
                      "matchedCards": [{"resourceType": kind, "resourceId": i} for kind, i in sorted(pickups & featured)]})
    # Reuse the existing recruitment rates, reward names and mission descriptions.
    systems = enrich_systems({"gachaPools": pools, "vipRanks": [], "studioUnits": [], "evidence": []}, source.root, source.locale)
    for evidence in systems["evidence"]:
        rows(evidence["table"])
    missions = systems["missions"]
    direct_ids = {r["_id"] for r in rows("MasterEventMission") if r.get("_eventId") == event_id}
    direct = [m for m in missions if m.get("sourceTable") == "MasterEventMission"
              and any(stage["id"] in direct_ids for stage in m["stages"])]
    passes = []
    event_name = normalized(title("MasterEvent", event))
    pass_tasks = rows("MasterSeasonPassMission")
    rewards = {r["_id"]: r for r in rows("MasterSeasonPassReward")}
    level_rows = rows("MasterSeasonPassLevel")
    reward_rows = rows("MasterSeasonPassLevelReward")
    for season in rows("MasterSeasonPass"):
        name = title("MasterSeasonPass", season)
        explicit = season.get("_eventId") == event_id
        matched = (not season.get("_eventId") and event_name and event_name in normalized(name)
                   and season.get("_startAt") == event.get("_startAt") and season.get("_endAt") == event.get("_endAt"))
        if not explicit and not matched:
            continue
        task_ids = {r["_id"] for r in pass_tasks if r.get("_seasonPassId") == season["_id"]}
        groups = [m for m in missions if m.get("sourceTable") == "MasterSeasonPassMission"
                  and any(stage["id"] in task_ids for stage in m["stages"])]
        for group in groups:
            first_task = next((r for r in pass_tasks if r["_id"] == group["stages"][0]["id"]), {})
            daily = first_task.get("_missionCategory") == 1
            cycle = ("Daily missions" if daily else "Event-period missions") if source.locale == "en" else ("每日任务" if daily else "期间累计任务")
            group["title"] = f"{name} · {cycle}"
        levels = []
        for level in sorted((r for r in level_rows if r.get("_group") == season.get("_levelGroup")), key=lambda r: r["_level"]):
            tracks = {False: [], True: []}
            for reward in reward_rows:
                if reward.get("_seasonPassId") == season["_id"] and reward.get("_level") == level["_level"]:
                    for identity in reward.get("_rewardIds", []):
                        if identity in rewards:
                            tracks[bool(reward.get("_isPremium"))].append(source.resource(rewards[identity]))
                        else:
                            source.warnings.add(f"missing_reference:MasterSeasonPassReward:{identity}")
            levels.append({"level": level["_level"], "points": level.get("_point"), "free": tracks[False], "premium": tracks[True]})
        passes.append({"id": season["_id"], "name": name, "startAt": season.get("_startAt"), "endAt": season.get("_endAt"),
                       "relationStatus": "explicit_id" if explicit else "matching_title_and_period",
                       "missions": groups, "levels": levels})
    return {"recruitment": pools, "missions": direct, "passes": passes}
