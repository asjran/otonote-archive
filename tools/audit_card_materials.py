"""Compare local card material projections against the selected formal Master tables."""
from collections import Counter
import json
from pathlib import Path


def audit(root: Path) -> dict:
    source = json.loads((root / "config/release-inputs.json").read_text())["environments"][0]
    master = root / source["masterRoot"]
    tables = {}
    def rows(name):
        if name not in tables:
            tables[name] = json.loads((master / f"{name}.json").read_text())["_allData"]
        return tables[name]

    generated = root / "site/src/data/generated"
    projections = json.loads((generated / "card-detail-projections.json").read_text())
    database = json.loads((generated / "game-database.json").read_text())
    profiles = {p["id"]: p for p in database["growthProfiles"]}
    characters = {r["_id"]: r for r in rows("MasterCharacter")}
    bands = {r["_id"]: r for r in rows("MasterBand")}
    rarity_fields = {2: "_rankUpItemIdForRarityR", 3: "_rankUpItemIdForRaritySR", 4: "_rankUpItemIdForRaritySSR", 10: "_rankUpItemIdForRarityBD"}
    def actual(requirements):
        return Counter((r["itemId"], r["amount"], r["usageKind"], r["stage"]) for r in requirements)

    errors, unresolved = [], []
    checked = 0
    for key, table, kind in (("memberCards", "MasterMemberCard", "member"), ("supportCards", "MasterSupportCard", "support")):
        sources = {r["_id"]: r for r in rows(table)}
        for projection in projections[key]:
            card_id = projection["cardId"]
            row = sources[int(card_id.rsplit("-", 1)[1])]
            if not projection["growthProfileId"]:
                unresolved.append({"cardId": card_id, "reason": "Cross-band rank material mapping is not verified"})
                continue
            expected = []
            if kind == "member":
                expected += [(f"item-{row['_rankUpItemID']}", r["_requiredRankUpItemCount"], "member_rank", r["_rank"])
                             for r in rows("MasterMemberCardRank") if r["_group"] == row["_memberCardRankGroup"] and r["_requiredRankUpItemCount"]]
                expected += [(f"item-{r['_itemId']}", r["_count"], "member_awake", r["_awakeCount"])
                             for r in rows("MasterMemberCardAwakeResource") if r["_group"] == row["_memberCardAwakeResourceGroup"]]
            else:
                band_ids = {characters[c]["_bandID"] for c in row["_characterIDs"]}
                if len(band_ids) != 1:
                    errors.append(f"{card_id}: ambiguous band material is presented as resolved")
                    continue
                item = bands[next(iter(band_ids))][rarity_fields[row["_rarity"]]]
                expected += [(f"item-{item}", r["_requiredRankUpItemCount"], "support_rank", r["_rank"])
                             for r in rows("MasterSupportCardRank") if r["_group"] == row["_supportCardRankGroup"] and r["_requiredRankUpItemCount"]]
            profile = profiles[projection["growthProfileId"]]
            if actual(profile["materialRequirements"]) != Counter(expected):
                errors.append(f"{card_id}: growth costs differ from Master")
            if kind == "member":
                for field in ("_liveSkillLevelResourceGroup", "_gekisouSkillLevelResourceGroup"):
                    expected += [(f"item-{r['_itemID']}", r["_count"], "skill_level", r["_level"])
                                 for r in rows("MasterSkillLevelResource") if r["_group"] == row[field]]
            if actual(projection["materialSummary"]) != Counter(expected):
                errors.append(f"{card_id}: combined costs differ from Master")
            level_group = row["_memberCardLevelGroup" if kind == "member" else "_supportCardLevelGroup"]
            exp = [(r["_level"], r["_exp"]) for r in rows("MasterMemberCardLevel" if kind == "member" else "MasterSupportCardLevel") if r["_group"] == level_group]
            if sorted((p["level"], p["rawExp"]) for p in profile["levelCurve"]) != sorted(exp):
                errors.append(f"{card_id}: experience differs from Master")
            checked += 1
    return {"sourceReleaseId": source["contentReleaseId"], "cardsChecked": checked,
            "memberCards": len(projections["memberCards"]), "supportCards": len(projections["supportCards"]),
            "errors": errors, "unresolved": unresolved}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    report = audit(root)
    path = root / "output/readiness/card-material-audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(bool(report["errors"]))
