#!/usr/bin/env python3
"""Build and validate stable page-responsibility database shards."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.artifact_registry import validate_artifact


SCHEMA_VERSION = 1


class DatabaseShardError(RuntimeError):
    """Raised when a shard would contain inconsistent references."""


@dataclass(frozen=True)
class DatabaseShardBuild:
    files: dict[str, dict[str, Any]]
    manifest: dict[str, Any]
    report: dict[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _record_ids(records: Iterable[Mapping[str, Any]], label: str) -> set[str]:
    ids = [str(record.get("id") or "") for record in records]
    if any(not value for value in ids):
        raise DatabaseShardError(f"{label} has empty id")
    if len(ids) != len(set(ids)):
        raise DatabaseShardError(f"{label} has duplicate id")
    return set(ids)


def _collection(
    release_id: str,
    kind: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contentReleaseId": release_id,
        "kind": kind,
        "recordCount": len(records),
        "sha256": _sha256(records),
        "records": records,
    }


def _detail(
    release_id: str,
    kind: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contentReleaseId": release_id,
        "kind": kind,
        "recordCount": 1,
        "sha256": _sha256(record),
        "record": record,
    }


def _skill_index(skill: Mapping[str, Any]) -> dict[str, Any]:
    levels = list(skill.get("levels", []))
    effects = [effect for level in levels for effect in level.get("effects", [])]
    return {
        key: skill.get(key)
        for key in (
            "id",
            "masterId",
            "kind",
            "name",
            "iconAssetId",
            "iconStatus",
            "publicationStatus",
            "interpretationStatus",
        )
    } | {
        "highestLevel": int(levels[-1].get("level", 0)) if levels else 0,
        "highestSummary": str(levels[-1].get("renderedSummary", "")) if levels else "",
        "effects": [
            {"type": effect_type, "name": name}
            for effect_type, name in sorted(
                {
                    (
                        int(effect.get("effectType", 0)),
                        str(effect.get("effectName", "")),
                    )
                    for effect in effects
                }
            )
        ],
        "targetIds": sorted(
            {
                str(target_id)
                for effect in effects
                for target_id in effect.get("targetIds", [])
            }
        ),
        "conditional": any(
            effect.get(field)
            for effect in effects
            for field in (
                "conditionGroupId",
                "releaseConditionGroupId",
                "triggerConditionGroupId",
                "cumulativeConditionId",
            )
        ),
        "relatedCardIds": list(skill.get("relatedCardIds", [])),
    }


def _item_index(item: Mapping[str, Any]) -> dict[str, Any]:
    usages = list(item.get("usages", []))
    return {
        key: item.get(key)
        for key in (
            "id",
            "masterId",
            "name",
            "phoneticName",
            "description",
            "typeCode",
            "maxOwned",
            "displayOrder",
            "availableFrom",
            "availableUntil",
            "iconAssetId",
            "catalogStatus",
        )
    } | {
        "usageKinds": sorted({str(usage.get("usageKind", "")) for usage in usages}),
        "relatedCardIds": sorted(
            {
                str(card_id)
                for usage in usages
                for card_id in usage.get("cardIds", [])
            }
        ),
    }


def _validate_references(
    database: Mapping[str, Any],
    projections: Mapping[str, Any],
) -> None:
    skills = list(database.get("skills", []))
    items = list(database.get("items", []))
    growth = list(database.get("growthProfiles", []))
    targets = list(database.get("targets", []))
    skill_ids = _record_ids(skills, "skills")
    item_ids = _record_ids(items, "items")
    growth_ids = _record_ids(growth, "growth profiles")
    target_ids = _record_ids(targets, "skill targets")
    cards = [
        *projections.get("memberCards", []),
        *projections.get("supportCards", []),
    ]
    card_ids = _record_ids(
        [{"id": card.get("cardId")} for card in cards], "card projections"
    )

    for card in cards:
        for reference in card.get("skillRefs", []):
            if reference.get("skillId") not in skill_ids:
                raise DatabaseShardError(
                    f"{card['cardId']} references missing skill {reference.get('skillId')}"
                )
        growth_id = card.get("growthProfileId")
        if growth_id and growth_id not in growth_ids:
            raise DatabaseShardError(
                f"{card['cardId']} references missing growth profile {growth_id}"
            )
        for material in card.get("materialSummary", []):
            if material.get("itemId") not in item_ids:
                raise DatabaseShardError(
                    f"{card['cardId']} references missing item {material.get('itemId')}"
                )
    for skill in skills:
        missing_cards = set(skill.get("relatedCardIds", [])) - card_ids
        if missing_cards:
            raise DatabaseShardError(
                f"{skill['id']} references missing cards {sorted(missing_cards)}"
            )
        for level in skill.get("levels", []):
            for effect in level.get("effects", []):
                missing_targets = set(effect.get("targetIds", [])) - target_ids
                if missing_targets:
                    raise DatabaseShardError(
                        f"{skill['id']} references missing targets {sorted(missing_targets)}"
                    )


def build_database_shards(
    database: Mapping[str, Any],
    projections: Mapping[str, Any],
    content_release_id: str,
) -> DatabaseShardBuild:
    if database.get("sourceReleaseId") != content_release_id:
        raise DatabaseShardError("database ContentRelease does not match shard release")
    _validate_references(database, projections)

    skills = [dict(record) for record in database.get("skills", [])]
    public_skills = [
        record for record in skills if record.get("publicationStatus") == "public"
    ]
    items = [dict(record) for record in database.get("items", [])]
    growth = [dict(record) for record in database.get("growthProfiles", [])]
    members = [dict(record) for record in projections.get("memberCards", [])]
    supports = [dict(record) for record in projections.get("supportCards", [])]
    files: dict[str, dict[str, Any]] = {
        "summary.json": _detail(
            content_release_id,
            "database-summary",
            {
                "sourceReleaseId": content_release_id,
                "quality": dict(database.get("quality", {})),
                "counts": {
                    "publicSkills": len(public_skills),
                    "items": len(items),
                    "growthProfiles": len(growth),
                    "memberCards": len(members),
                    "supportCards": len(supports),
                },
            },
        ),
        "skills-index.json": _collection(
            content_release_id,
            "skill-index",
            [_skill_index(record) for record in public_skills],
        ),
        "items-index.json": _collection(
            content_release_id,
            "item-index",
            [_item_index(record) for record in items],
        ),
        "growth-index.json": _collection(
            content_release_id,
            "growth-index",
            [
                {
                    "id": record["id"],
                    "cardKind": record.get("cardKind"),
                    "sourceCardIds": record.get("sourceCardIds", []),
                    "maxLevel": max(
                        (int(point.get("level", 0)) for point in record.get("levelCurve", [])),
                        default=0,
                    ),
                }
                for record in growth
            ],
        ),
        "targets.json": _collection(
            content_release_id,
            "skill-targets",
            [dict(record) for record in database.get("targets", [])],
        ),
        "conditions.json": _detail(
            content_release_id,
            "skill-conditions",
            {
                "conditions": list(database.get("conditions", [])),
                "conditionGroups": list(database.get("conditionGroups", [])),
                "cumulativeConditions": list(database.get("cumulativeConditions", [])),
            },
        ),
        "skill-level-resources.json": _collection(
            content_release_id,
            "skill-level-resources",
            [dict(record) for record in database.get("skillLevelResourceProfiles", [])],
        ),
        "member-cards-index.json": _collection(
            content_release_id,
            "member-card-index",
            [
                {
                    "cardId": record["cardId"],
                    "growthProfileId": record.get("growthProfileId"),
                    "skillIds": [ref.get("skillId") for ref in record.get("skillRefs", [])],
                }
                for record in members
            ],
        ),
        "support-cards-index.json": _collection(
            content_release_id,
            "support-card-index",
            [
                {
                    "cardId": record["cardId"],
                    "growthProfileId": record.get("growthProfileId"),
                    "skillIds": [ref.get("skillId") for ref in record.get("skillRefs", [])],
                }
                for record in supports
            ],
        ),
    }
    for record in public_skills:
        files[f"skills/{record['id']}.json"] = _detail(
            content_release_id, "skill-detail", record
        )
    for record in items:
        files[f"items/{record['id']}.json"] = _detail(
            content_release_id, "item-detail", record
        )
    for record in growth:
        files[f"growth/{record['id']}.json"] = _detail(
            content_release_id, "growth-detail", record
        )
    for record in members:
        files[f"member-cards/{record['cardId']}.json"] = _detail(
            content_release_id, "member-card-detail", record
        )
    for record in supports:
        files[f"support-cards/{record['cardId']}.json"] = _detail(
            content_release_id, "support-card-detail", record
        )

    entries = []
    total_bytes = 0
    for path, value in sorted(files.items()):
        encoded = _canonical_bytes(value)
        total_bytes += len(encoded)
        entries.append(
            {
                "path": path,
                "kind": value["kind"],
                "recordCount": value["recordCount"],
                "sha256": value["sha256"],
                "byteSize": len(encoded),
            }
        )
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "contentReleaseId": content_release_id,
        "fileCount": len(entries),
        "totalBytes": total_bytes,
        "files": entries,
    }
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "passed",
        "contentReleaseId": content_release_id,
        "fileCount": len(entries),
        "totalBytes": total_bytes,
        "monolithBytes": len(_canonical_bytes(database)),
        "listIndexBytes": sum(
            entry["byteSize"]
            for entry in entries
            if entry["path"]
            in {"skills-index.json", "items-index.json", "growth-index.json"}
        ),
        "publicSkillCount": len(public_skills),
        "itemCount": len(items),
        "growthProfileCount": len(growth),
        "memberCardCount": len(members),
        "supportCardCount": len(supports),
        "referenceErrors": [],
    }
    return DatabaseShardBuild(files=files, manifest=manifest, report=report)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_database_shard_tree(root: Path, content_release_id: str) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise DatabaseShardError(f"shard manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contentReleaseId") != content_release_id:
        raise DatabaseShardError("shard manifest ContentRelease mismatch")
    files = list(manifest.get("files", []))
    if int(manifest.get("fileCount", -1)) != len(files):
        raise DatabaseShardError("shard manifest file count mismatch")
    for entry in files:
        relative = str(entry.get("path", ""))
        path = root / relative
        if not path.is_file():
            raise DatabaseShardError(f"shard file missing: {relative}")
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        if wrapper.get("contentReleaseId") != content_release_id:
            raise DatabaseShardError(
                f"shard ContentRelease mismatch: {relative}"
            )
        payload = wrapper.get("records") if "records" in wrapper else wrapper.get("record")
        digest = _sha256(payload)
        if digest != wrapper.get("sha256") or digest != entry.get("sha256"):
            raise DatabaseShardError(f"shard digest mismatch: {relative}")
        expected_count = len(payload) if isinstance(payload, list) else 1
        if wrapper.get("recordCount") != expected_count:
            raise DatabaseShardError(f"shard record count mismatch: {relative}")


def write_database_shards(
    database: Mapping[str, Any],
    projections: Mapping[str, Any],
    content_release_id: str,
    generated_root: Path,
    public_root: Path,
    report_path: Path,
    *,
    additional_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    built = build_database_shards(database, projections, content_release_id)
    validate_artifact("database-shards/manifest.json", built.manifest)
    roots = tuple(
        dict.fromkeys((generated_root, public_root, *additional_roots))
    )
    for root in roots:
        previous = root / "manifest.json"
        if previous.is_file():
            old = json.loads(previous.read_text(encoding="utf-8"))
            for entry in old.get("files", []):
                path = root / str(entry.get("path", ""))
                if path.is_file() and str(entry.get("path")) not in built.files:
                    path.unlink()
        for relative, value in built.files.items():
            _write_json(root / relative, value)
        _write_json(root / "manifest.json", built.manifest)
        validate_database_shard_tree(root, content_release_id)
    _write_json(report_path, built.report)
    return built.report
