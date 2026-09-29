"""Refresh card diaries and growth projections for the selected local release."""
from __future__ import annotations

import json
from pathlib import Path

from tools.database_shards import write_database_shards
from tools.game_database import build_game_database
from tools.master_catalog import build_master_entities, load_master_data


def refresh_card_details(root: Path, source: dict, catalog: dict) -> None:
    generated = root / "site/src/data/generated"
    public = root / "site/public/data"
    release_id = source["contentReleaseId"]
    master_root = root / source["masterRoot"]
    entities, _ = build_master_entities(
        load_master_data(master_root), [], {}, release_id,
        catalog.get("projectionContext", {}).get("locale", "zh-CN"),
    )
    diaries = {card["id"]: card["diary"] for card in entities["supportCards"]}
    for card in catalog["supportCards"]:
        card["diary"] = diaries.get(card["id"], "")

    database = json.loads((generated / "game-database.json").read_text())
    projections = json.loads((generated / "card-detail-projections.json").read_text())
    if database["sourceReleaseId"] != release_id:
        raise ValueError("Card database does not match the selected release")
    built = build_game_database(master_root, release_id)
    database["growthProfiles"] = built.database["growthProfiles"]
    database["skillLevelResourceProfiles"] = built.database["skillLevelResourceProfiles"]
    fresh_items = {item["id"]: item for item in built.database["items"]}
    for item in database["items"]:
        for field in ("acquisitionSources", "liveDrops"):
            item[field] = fresh_items[item["id"]][field]
    fresh_skills = {skill["id"]: skill for skill in built.database["skills"]}
    for skill in database["skills"]:
        fresh = fresh_skills[skill["id"]]
        summaries = {level["level"]: level["renderedSummary"] for level in fresh["levels"]}
        for level in skill["levels"]:
            level["renderedSummary"] = summaries[level["level"]]
        skill["interpretationStatus"] = fresh["interpretationStatus"]
    for kind in ("memberCards", "supportCards"):
        fresh = {card["cardId"]: card for card in built.card_projections[kind]}
        for card in projections[kind]:
            for field in ("growthProfileId", "growthSummary", "skillRefs", "materialSummary", "skillSummaries"):
                card[field] = fresh[card["cardId"]][field]

    for base in (generated, public):
        for name, data in (("catalog.json", catalog), ("game-database.json", database),
                           ("card-detail-projections.json", projections)):
            path = base / name
            text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            if not path.exists() or path.read_text() != text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    write_database_shards(
        database, projections, release_id,
        generated / "database-shards", public / "database-shards",
        root / "output/readiness/card-detail-shards.json",
    )
