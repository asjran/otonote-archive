"""Normalize card-related Master tables into a public game database."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.resource_pipeline.localization import (
    DEFAULT_FALLBACK_ORDER,
    extract_localized_text,
    resolve_localized_text,
)


class GameDatabaseError(ValueError):
    """Raised when game database inputs violate publishing invariants."""


@dataclass(frozen=True)
class GameDatabaseBuild:
    database: dict[str, Any]
    card_projections: dict[str, Any]
    warnings: list[str]


REQUIRED_TABLES = (
    "MasterText",
    "MasterBand",
    "MasterCharacter",
    "MasterMemberCard",
    "MasterSupportCard",
    "MasterLeaderSkill",
    "MasterLeaderSkillEffect",
    "MasterLiveSkill",
    "MasterLiveSkillEffect",
    "MasterSupportSkill",
    "MasterSupportSkillEffect",
    "MasterGekisouSkill",
    "MasterGekisouSkillEffect",
    "MasterGekisouSupportSkill",
    "MasterGekisouSupportSkillEffect",
    "MasterSkillCondition",
    "MasterSkillConditionSet",
    "MasterSkillCumulativeCondition",
    "MasterSkillEffectSetting",
    "MasterSkillTarget",
    "MasterSkillLevelResource",
    "MasterSkillIcon",
    "MasterMemberCardLevel",
    "MasterMemberCardLevelLimit",
    "MasterMemberCardRank",
    "MasterMemberCardAwake",
    "MasterMemberCardAwakeResource",
    "MasterSupportCardLevel",
    "MasterSupportCardRank",
    "MasterItem",
)

SUPPORT_RANK_ITEM_FIELDS = {
    2: "_rankUpItemIdForRarityR",
    3: "_rankUpItemIdForRaritySR",
    4: "_rankUpItemIdForRaritySSR",
    10: "_rankUpItemIdForRarityBD",
}

SKILL_SPECS = (
    (
        "leader",
        "MasterLeaderSkill",
        "MasterLeaderSkillEffect",
        "_leaderSkillID",
    ),
    (
        "live",
        "MasterLiveSkill",
        "MasterLiveSkillEffect",
        "_liveSkillID",
    ),
    (
        "support",
        "MasterSupportSkill",
        "MasterSupportSkillEffect",
        "_supportSkillID",
    ),
    (
        "gekisou",
        "MasterGekisouSkill",
        "MasterGekisouSkillEffect",
        "_gekisouSkillID",
    ),
    (
        "gekisou_support",
        "MasterGekisouSupportSkill",
        "MasterGekisouSupportSkillEffect",
        "_gekisouSupportSkillID",
    ),
)

SKILL_TEMPLATE_PATTERN = re.compile(
    r"\{effects\[(?P<index>\d+)\]\."
    r"(?P<field>value|time|maxValue|limitCount|EffectExecuteLimitCount)"
    r"(?:/(?P<divisor>\d+))?"
    r"(?::F(?P<precision>\d+))?\}"
)


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise GameDatabaseError(f"missing Master table: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise GameDatabaseError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise GameDatabaseError(f"{name} must contain an _allData array")
    return rows


def _unique_index(
    rows: Iterable[dict[str, Any]],
    field: str,
    label: str,
    key_type: type[int] | type[str] = int,
) -> dict[Any, dict[str, Any]]:
    index: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, key_type):
            raise GameDatabaseError(
                f"{label} row has invalid {field}: {key!r}"
            )
        if key in index:
            raise GameDatabaseError(f"duplicate {label} {field}: {key}")
        index[key] = row
    return index


def _text_values(
    texts: Mapping[str, dict[str, Any]],
    text_id: Any,
) -> list[str]:
    if not isinstance(text_id, str) or not text_id:
        return []
    row = texts.get(text_id)
    if not row:
        return []
    localized = extract_localized_text(row)
    return [
        localized[locale]
        for locale in DEFAULT_FALLBACK_ORDER
        if locale in localized
    ]


def _resolve_text(
    texts: Mapping[str, dict[str, Any]],
    text_id: Any,
    fallback: str,
) -> str:
    row = texts.get(text_id) if isinstance(text_id, str) else None
    return resolve_localized_text(row, "zh-CN", fallback).text


def _skill_id(kind: str, master_id: int) -> str:
    return f"{kind.replace('_', '-')}-skill-{master_id}"


def _render_skill_template(
    template: str,
    effects: list[dict[str, Any]],
    condition_groups: Mapping[int, list[list[dict[str, Any]]]] | None = None,
    cumulative_conditions: Mapping[int, dict[str, Any]] | None = None,
) -> tuple[str, bool]:
    unsupported = False

    def replace(match: re.Match[str]) -> str:
        nonlocal unsupported
        index = int(match.group("index"))
        if index >= len(effects):
            unsupported = True
            return match.group(0)
        effect = effects[index]
        field = match.group("field")
        values = {
            "time": effect.get("durationSeconds"),
            "value": effect.get("rawValue"),
            "maxValue": effect.get("rawMaxValue"),
            "limitCount": effect.get("effectLimitCount"),
            "EffectExecuteLimitCount": effect.get("executeLimitCount"),
        }
        value = values[field]
        if not isinstance(value, (int, float)):
            unsupported = True
            return match.group(0)
        divisor = int(match.group("divisor") or "1")
        precision_text = match.group("precision")
        if precision_text is None:
            divided = value / divisor
            return (
                str(int(divided))
                if float(divided).is_integer()
                else str(divided)
            )
        precision = int(precision_text)
        return f"{value / divisor:.{precision}f}"

    def replace_condition(match: re.Match[str]) -> str:
        expression = match.group(1)
        path = re.fullmatch(
            r"effects\[(\d+)\]\.(?:(con|tCon)\[(\d+)\]\[(\d+)\]|(cCon))\."
            r"(?:values\[(\d+)\](?::F(\d+))?|targets\[(\d+)\]\.name)",
            expression,
        )
        if not path:
            return match.group(0)
        index, kind, set_index, condition_index, cumulative, value_index, precision, target_index = path.groups()
        try:
            effect = effects[int(index)]
            if cumulative:
                condition = (cumulative_conditions or {})[effect["cumulativeConditionId"]]
            else:
                group_id = effect["triggerConditionGroupId" if kind == "tCon" else "conditionGroupId"]
                condition = (condition_groups or {})[group_id][int(set_index)][int(condition_index)]
            if target_index is not None:
                name = condition["targets"][int(target_index)]["name"]
                return name if name else match.group(0)
            value = condition["values"][int(value_index)]
            if not isinstance(value, (int, float)):
                return match.group(0)
            return f"{value:.{int(precision)}f}" if precision is not None else f"{value:g}"
        except (KeyError, IndexError):
            return match.group(0)

    def replace_time_branch(match: re.Match[str]) -> str:
        # Accept only the game's duration/string forms, never execute template code.
        branch = re.fullmatch(
            r'0 < effects\[(\d+)\]\.time \? (?:"([^"{}]*)"|effects\[(\d+)\]\.time ~ "([^"{}]*)") : "([^"{}]*)"',
            match.group(1),
        )
        if not branch:
            return match.group(0)
        index, literal, time_index, suffix, otherwise = branch.groups()
        if int(index) >= len(effects) or (time_index is not None and time_index != index):
            return match.group(0)
        duration = effects[int(index)].get("durationSeconds")
        if not isinstance(duration, (int, float)):
            return match.group(0)
        if duration <= 0:
            return otherwise
        return literal if literal is not None else f"{duration:g}{suffix}"

    rendered = SKILL_TEMPLATE_PATTERN.sub(replace, template)
    rendered = re.sub(r"\{([^{}]+)\}", replace_condition, rendered)
    rendered = re.sub(r"\{([^{}]+)\}", replace_time_branch, rendered)
    rendered = re.sub(r"<color=[^>]+>", "", rendered)
    rendered = rendered.replace("</color>", "")
    if re.search(r"\{[^{}]+\}", rendered):
        unsupported = True
        rendered = re.sub(r"\{[^{}]+\}", "〔指定条件〕", rendered)
    return rendered, not unsupported


def _skill_template_conditions(tables, texts):
    """Resolve only explicit Master references, preserving nested source order."""
    bands = {row["_id"]: row for row in tables["MasterBand"]}
    targets = {}
    for row in tables["MasterSkillTarget"]:
        band = bands.get(row.get("_bandID")) if row.get("_skillTargetType") == 3 else None
        targets[row["_id"]] = {"name": _resolve_text(texts, band.get("_nameTextID") if band else None, "")}

    def condition(row):
        return {
            "values": row.get("_conditionValues") or [],
            "targets": [targets.get(target_id, {"name": ""}) for target_id in row.get("_conditionTargetIDs") or []],
        }

    conditions = {row["_id"]: condition(row) for row in tables["MasterSkillCondition"]}
    groups = defaultdict(list)
    for row in tables["MasterSkillConditionSet"]:
        groups[row["_group"]].append([conditions.get(condition_id, {}) for condition_id in row["_conditionIds"]])
    cumulative = {row["_id"]: condition(row) for row in tables["MasterSkillCumulativeCondition"]}
    return groups, cumulative


def _normalize_target(row: dict[str, Any]) -> dict[str, Any]:
    master_id = int(row["_id"])
    character_id = int(row.get("_characterID") or 0)
    band_id = int(row.get("_bandID") or 0)
    return {
        "id": f"skill-target-{master_id}",
        "masterId": master_id,
        "targetType": int(row.get("_skillTargetType") or 0),
        "characterId": (
            f"character-{character_id}" if character_id else None
        ),
        "bandId": f"band-{band_id}" if band_id else None,
        "cardTypeCode": int(row.get("_cardType") or 0),
        "tagId": int(row.get("_tagID") or 0),
        "judgementCode": int(row.get("_judgement") or 0),
        "liveMusicTypeCode": int(row.get("_liveMusicType") or 0),
        "skillTypeCode": int(row.get("_skillType") or 0),
        "skillGroupId": int(row.get("_skillGroupID") or 0),
        "missionTypeCode": int(row.get("_gekisouMissionType") or 0),
        "liveSkillCategoryCodes": list(
            row.get("_liveSkillCategories") or []
        ),
        "gekisouSkillCategoryCodes": list(
            row.get("_gekisouSkillCategories") or []
        ),
        "interpretationStatus": "partial",
    }


def _build_conditions(
    tables: Mapping[str, list[dict[str, Any]]],
    target_ids: set[int],
    referenced_group_ids: set[int],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    warnings: list[str] = []
    condition_rows = _unique_index(
        tables["MasterSkillCondition"],
        "_id",
        "skill condition",
    )
    conditions = []
    for master_id, row in sorted(condition_rows.items()):
        raw_target_ids = row.get("_conditionTargetIDs") or []
        if not isinstance(raw_target_ids, list) or not all(
            isinstance(target_id, int) for target_id in raw_target_ids
        ):
            raise GameDatabaseError(
                f"skill condition {master_id} has invalid target ids"
            )
        missing_targets = set(raw_target_ids) - target_ids
        if missing_targets:
            raise GameDatabaseError(
                f"skill condition {master_id} references missing targets "
                f"{sorted(missing_targets)}"
            )
        conditions.append(
            {
                "id": f"skill-condition-{master_id}",
                "masterId": master_id,
                "conditionType": int(row.get("_conditionType") or 0),
                "rawValues": list(row.get("_conditionValues") or []),
                "isPositive": bool(row.get("_isPositive")),
                "targetIds": [
                    f"skill-target-{target_id}"
                    for target_id in raw_target_ids
                ],
                "interpretationStatus": "partial",
            }
        )

    sets_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_set_ids: set[int] = set()
    for row in tables["MasterSkillConditionSet"]:
        source_set_id = row.get("_id")
        group_id = row.get("_group")
        raw_condition_ids = row.get("_conditionIds") or []
        if not isinstance(source_set_id, int) or source_set_id in seen_set_ids:
            raise GameDatabaseError(
                f"invalid or duplicate skill condition set id: "
                f"{source_set_id!r}"
            )
        seen_set_ids.add(source_set_id)
        if not isinstance(group_id, int):
            raise GameDatabaseError(
                f"skill condition set {source_set_id} has invalid group"
            )
        if not isinstance(raw_condition_ids, list) or not all(
            isinstance(condition_id, int)
            for condition_id in raw_condition_ids
        ):
            raise GameDatabaseError(
                f"skill condition set {source_set_id} has invalid conditions"
            )
        missing_conditions = set(raw_condition_ids) - set(condition_rows)
        if missing_conditions:
            message = (
                f"skill condition set {source_set_id} references missing "
                f"conditions {sorted(missing_conditions)}"
            )
            if group_id in referenced_group_ids:
                raise GameDatabaseError(message)
            warnings.append(message)
            continue
        sets_by_group[group_id].append(
            {
                "sourceSetId": source_set_id,
                "conditionIds": [
                    f"skill-condition-{condition_id}"
                    for condition_id in raw_condition_ids
                ],
            }
        )
    condition_groups = [
        {
            "groupId": group_id,
            "sets": sets,
            "combinationStatus": "unverified",
        }
        for group_id, sets in sorted(sets_by_group.items())
    ]

    cumulative_rows = _unique_index(
        tables["MasterSkillCumulativeCondition"],
        "_id",
        "skill cumulative condition",
    )
    cumulative_conditions = []
    for master_id, row in sorted(cumulative_rows.items()):
        raw_target_ids = row.get("_conditionTargetIDs") or []
        if not isinstance(raw_target_ids, list) or not all(
            isinstance(target_id, int) for target_id in raw_target_ids
        ):
            raise GameDatabaseError(
                f"skill cumulative condition {master_id} has invalid targets"
            )
        missing_targets = set(raw_target_ids) - target_ids
        if missing_targets:
            raise GameDatabaseError(
                f"skill cumulative condition {master_id} references missing "
                f"targets {sorted(missing_targets)}"
            )
        cumulative_conditions.append(
            {
                "id": f"skill-cumulative-condition-{master_id}",
                "masterId": master_id,
                "conditionType": int(
                    row.get("_skillCumulativeConditionType") or 0
                ),
                "rawValues": list(row.get("_conditionValues") or []),
                "targetIds": [
                    f"skill-target-{target_id}"
                    for target_id in raw_target_ids
                ],
                "maxCumulativeCount": int(
                    row.get("_maxCumulativeCount") or 0
                ),
                "interpretationStatus": "partial",
            }
        )
    return conditions, condition_groups, cumulative_conditions, warnings


def _referenced_condition_group_ids(
    tables: Mapping[str, list[dict[str, Any]]],
) -> set[int]:
    fields = (
        "_skillConditionGroup",
        "_skillReleaseConditionGroup",
        "_skillTriggerConditionGroup",
        "_effectExecuteLimitResetConditionGroup",
    )
    group_ids: set[int] = set()
    for _, _, effect_table, _ in SKILL_SPECS:
        for row in tables[effect_table]:
            for field in fields:
                value = row.get(field)
                if isinstance(value, int) and value:
                    group_ids.add(value)
    return group_ids


def _normalize_effect(
    row: dict[str, Any],
    source_order: int,
    effect_settings: Mapping[int, dict[str, Any]],
    texts: Mapping[str, dict[str, Any]],
    target_ids: set[int],
    condition_group_ids: set[int],
    cumulative_condition_ids: set[int],
) -> dict[str, Any]:
    raw_target_ids = row.get("_skillTargetIDs") or []
    if not isinstance(raw_target_ids, list) or not all(
        isinstance(target_id, int) for target_id in raw_target_ids
    ):
        raise GameDatabaseError(
            f"skill effect {row.get('_id')} has invalid target ids"
        )
    missing_targets = set(raw_target_ids) - target_ids
    if missing_targets:
        raise GameDatabaseError(
            f"skill effect {row.get('_id')} references missing targets "
            f"{sorted(missing_targets)}"
        )
    effect_type = int(row.get("_skillEffectType") or 0)
    setting = effect_settings.get(effect_type)
    condition_fields = (
        "_skillConditionGroup",
        "_skillReleaseConditionGroup",
        "_skillTriggerConditionGroup",
        "_effectExecuteLimitResetConditionGroup",
    )
    for field in condition_fields:
        group_id = int(row.get(field) or 0)
        if group_id and group_id not in condition_group_ids:
            raise GameDatabaseError(
                f"skill effect {row.get('_id')} references missing "
                f"condition group {group_id}"
            )
    cumulative_condition_id = int(
        row.get("_skillCumulativeConditionID") or 0
    )
    if (
        cumulative_condition_id
        and cumulative_condition_id not in cumulative_condition_ids
    ):
        raise GameDatabaseError(
            f"skill effect {row.get('_id')} references missing cumulative "
            f"condition {cumulative_condition_id}"
        )
    return {
        "sourceEffectId": int(row["_id"]),
        "sourceOrder": source_order,
        "effectType": effect_type,
        "effectName": _resolve_text(
            texts,
            setting.get("_nameTextId") if setting else None,
            f"Effect {effect_type}",
        ),
        "rawValue": int(row.get("_effectValue") or 0),
        "rawMaxValue": int(row.get("_maxEffectValue") or 0),
        "durationSeconds": float(row.get("_activationTimeSecond") or 0),
        "effectLimitCount": int(row.get("_effectLimitCount") or 0),
        "conditionGroupId": int(row.get("_skillConditionGroup") or 0),
        "releaseConditionGroupId": int(
            row.get("_skillReleaseConditionGroup") or 0
        ),
        "triggerConditionGroupId": int(
            row.get("_skillTriggerConditionGroup") or 0
        ),
        "triggerTypeCode": int(row.get("_skillTriggerType") or 0),
        "targetIds": [
            f"skill-target-{target_id}" for target_id in raw_target_ids
        ],
        "cumulativeConditionId": cumulative_condition_id,
        "executeLimitCount": int(
            row.get("_effectExecuteLimitCount") or 0
        ),
        "executeLimitResetConditionGroupId": int(
            row.get("_effectExecuteLimitResetConditionGroup") or 0
        ),
        "interpretationStatus": "identified" if setting else "partial",
    }


def _build_skills(
    tables: Mapping[str, list[dict[str, Any]]],
    texts: Mapping[str, dict[str, Any]],
    icon_asset_ids: Mapping[str, str],
    condition_group_ids: set[int],
    cumulative_condition_ids: set[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    template_conditions, template_cumulative = _skill_template_conditions(tables, texts)
    icon_rows = _unique_index(
        tables["MasterSkillIcon"],
        "_id",
        "skill icon",
    )
    effect_settings = {
        int(row["_skillEffectType"]): row
        for row in tables["MasterSkillEffectSetting"]
    }
    target_ids = {
        int(row["_id"]) for row in tables["MasterSkillTarget"]
    }
    skills: list[dict[str, Any]] = []

    for kind, definition_table, effect_table, effect_foreign_key in SKILL_SPECS:
        definitions = _unique_index(
            tables[definition_table],
            "_id",
            f"{kind} skill",
        )
        effects_by_skill: dict[int, list[tuple[int, dict[str, Any]]]] = (
            defaultdict(list)
        )
        seen_effect_ids: set[int] = set()
        for source_order, row in enumerate(tables[effect_table]):
            effect_id = row.get("_id")
            if not isinstance(effect_id, int) or effect_id in seen_effect_ids:
                raise GameDatabaseError(
                    f"invalid or duplicate {effect_table} effect id: "
                    f"{effect_id!r}"
                )
            seen_effect_ids.add(effect_id)
            skill_master_id = row.get(effect_foreign_key)
            if not isinstance(skill_master_id, int):
                raise GameDatabaseError(
                    f"{effect_table} row has invalid {effect_foreign_key}: "
                    f"{skill_master_id!r}"
                )
            if skill_master_id not in definitions:
                warnings.append(
                    f"{effect_table} effect {row.get('_id')} references "
                    f"missing {kind} skill {skill_master_id}"
                )
                continue
            effects_by_skill[skill_master_id].append((source_order, row))

        for master_id, definition in sorted(definitions.items()):
            template = _resolve_text(
                texts,
                definition.get("_descriptionTextFormatID"),
                "",
            )
            normalized_by_level: dict[int, list[dict[str, Any]]] = (
                defaultdict(list)
            )
            for source_order, row in effects_by_skill.get(master_id, []):
                level = int(row.get("_level") or 0)
                normalized_by_level[level].append(
                    _normalize_effect(
                        row,
                        source_order,
                        effect_settings,
                        texts,
                        target_ids,
                        condition_group_ids,
                        cumulative_condition_ids,
                    )
                )
            levels = []
            fully_interpreted = True
            for level, effects in sorted(normalized_by_level.items()):
                summary, interpreted = _render_skill_template(
                    template,
                    effects,
                    template_conditions,
                    template_cumulative,
                )
                fully_interpreted = fully_interpreted and interpreted and all(
                    effect["interpretationStatus"] == "identified"
                    for effect in effects
                )
                levels.append(
                    {
                        "level": level,
                        "effects": effects,
                        "renderedSummary": summary,
                        "materialRequirements": [],
                    }
                )
            skill_id = _skill_id(kind, master_id)
            if not fully_interpreted and levels:
                warnings.append(f"{skill_id} has partially interpreted effects")
            icon_id = int(definition.get("_skillIconID") or 0)
            icon_row = icon_rows.get(icon_id)
            icon_name = (
                str(icon_row.get("_normalIconAssetName") or "")
                if icon_row
                else ""
            )
            skills.append(
                {
                    "id": skill_id,
                    "masterId": master_id,
                    "kind": kind,
                    "name": _resolve_text(
                        texts,
                        definition.get("_nameTextID"),
                        f"{kind.replace('_', ' ').title()} Skill {master_id}",
                    ),
                    "descriptionTemplate": template,
                    "iconId": icon_id,
                    "iconAssetId": icon_asset_ids.get(icon_name),
                    "categoryCodes": list(
                        definition.get("_skillCategories") or []
                    ),
                    "missionTypeCode": int(
                        definition.get("_gekisouMissionType") or 0
                    ),
                    "executionTimingCode": int(
                        definition.get("_gekisouSupportSkillExecTiming") or 0
                    ),
                    "levels": levels,
                    "relatedCardIds": [],
                    "sourceReleaseIds": [],
                    "interpretationStatus": (
                        "identified" if fully_interpreted else "partial"
                    ),
                }
            )
    return skills, warnings


def _skill_ref(
    slot: str,
    kind: str,
    master_id: Any,
    level_resource_group: Any = 0,
) -> dict[str, Any] | None:
    if not isinstance(master_id, int):
        raise GameDatabaseError(f"{slot} has invalid skill id: {master_id!r}")
    if master_id == 0:
        return None
    return {
        "slot": slot,
        "skillId": _skill_id(kind, master_id),
        "levelResourceGroup": int(level_resource_group or 0),
    }


def _build_items(
    tables: Mapping[str, list[dict[str, Any]]],
    texts: Mapping[str, dict[str, Any]],
    icon_asset_ids: Mapping[str, str],
    release_id: str,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    item_rows = _unique_index(
        tables["MasterItem"],
        "_id",
        "item",
    )
    items = []
    items_by_master_id: dict[int, dict[str, Any]] = {}
    for master_id, row in sorted(item_rows.items()):
        image_path = str(row.get("_imagePath") or "")
        icon_name = image_path.rsplit("/", 1)[-1]
        icon_asset_id = icon_asset_ids.get(
            image_path,
            icon_asset_ids.get(icon_name),
        )
        item = {
            "id": f"item-{master_id}",
            "masterId": master_id,
            "name": _resolve_text(
                texts,
                row.get("_nameTextId"),
                f"Item {master_id}",
            ),
            "phoneticName": _resolve_text(
                texts,
                row.get("_phoneticNameTextId"),
                "",
            ),
            "description": _resolve_text(
                texts,
                row.get("_descriptionTextId"),
                "",
            ),
            "typeCode": int(row.get("_type") or 0),
            "inventoryDisplayGroup": int(
                row.get("_inventoryDisplayGroup") or 0
            ),
            "value": int(row.get("_value") or 0),
            "maxOwned": int(row.get("_max") or 0),
            "displayOrder": int(row.get("_orderNum") or 0),
            "displayTargetIds": list(row.get("_displayTargetIds") or []),
            "availableFrom": str(row.get("_startAt") or ""),
            "availableUntil": str(row.get("_endAt") or ""),
            "imagePath": image_path,
            "iconAssetId": icon_asset_id,
            "usages": [],
            "sourceReleaseIds": [release_id],
            "catalogStatus": (
                "identified" if icon_asset_id else "missing_asset"
            ),
        }
        items.append(item)
        items_by_master_id[master_id] = item
    return items, items_by_master_id


def _rows_by_group(
    rows: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group = row.get("_group")
        if not isinstance(group, int):
            raise GameDatabaseError(
                f"growth row has invalid _group: {group!r}"
            )
        grouped[group].append(row)
    return dict(grouped)


def _require_group(
    groups: Mapping[int, list[dict[str, Any]]],
    group_id: int,
    label: str,
) -> list[dict[str, Any]]:
    if group_id == 0:
        return []
    rows = groups.get(group_id)
    if rows is None:
        raise GameDatabaseError(f"missing {label} group {group_id}")
    return rows


def _rates(row: Mapping[str, Any]) -> dict[str, int]:
    return {
        "performance": int(row.get("_performanceRate") or 0),
        "technic": int(row.get("_technicRate") or 0),
        "visual": int(row.get("_visualRate") or 0),
    }


def _material_requirement(
    item_master_id: int,
    amount: int,
    usage_kind: str,
    stage: int,
    source_entity_id: str,
    source_group_id: int,
    card_ids: list[str],
) -> dict[str, Any]:
    return {
        "itemId": f"item-{item_master_id}",
        "amount": amount,
        "usageKind": usage_kind,
        "stage": stage,
        "sourceEntityId": source_entity_id,
        "sourceGroupId": source_group_id,
        "cardIds": sorted(card_ids),
        "interpretationStatus": "partial",
    }


def _build_growth_profiles(
    tables: Mapping[str, list[dict[str, Any]]],
    items_by_master_id: Mapping[int, dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[str],
]:
    member_levels = _rows_by_group(tables["MasterMemberCardLevel"])
    member_ranks = _rows_by_group(tables["MasterMemberCardRank"])
    member_awakes = _rows_by_group(tables["MasterMemberCardAwake"])
    member_awake_resources = _rows_by_group(
        tables["MasterMemberCardAwakeResource"]
    )
    support_levels = _rows_by_group(tables["MasterSupportCardLevel"])
    support_ranks = _rows_by_group(tables["MasterSupportCardRank"])
    characters_by_master_id = _unique_index(
        tables["MasterCharacter"],
        "_id",
        "character",
    )
    bands_by_master_id = _unique_index(
        tables["MasterBand"],
        "_id",
        "band",
    )

    limits_by_rarity: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tables["MasterMemberCardLevelLimit"]:
        rarity = row.get("_rarity")
        if not isinstance(rarity, int):
            raise GameDatabaseError(
                f"member level limit has invalid rarity: {rarity!r}"
            )
        limits_by_rarity[rarity].append(row)

    member_cards_by_key: dict[
        tuple[int, int, int, int, int, int],
        list[str],
    ] = defaultdict(list)
    support_cards_by_key: dict[tuple[int, int, int, int], list[str]] = (
        defaultdict(list)
    )
    warnings: list[str] = []
    for row in tables["MasterMemberCard"]:
        master_id = int(row["_id"])
        key = (
            int(row.get("_memberCardLevelGroup") or 0),
            int(row.get("_memberCardRankGroup") or 0),
            int(row.get("_memberCardAwakeGroup") or 0),
            int(row.get("_memberCardAwakeResourceGroup") or 0),
            int(row.get("_rarity") or 0),
            int(row.get("_rankUpItemID") or 0),
        )
        if any(
            (
                key[0],
                key[1],
                key[2],
                key[3],
                key[5],
            )
        ):
            member_cards_by_key[key].append(f"member-card-{master_id}")
    for row in tables["MasterSupportCard"]:
        master_id = int(row["_id"])
        level_group = int(row.get("_supportCardLevelGroup") or 0)
        rank_group = int(row.get("_supportCardRankGroup") or 0)
        if not any((level_group, rank_group)):
            continue
        character_ids = row.get("_characterIDs")
        if not isinstance(character_ids, list) or not character_ids:
            raise GameDatabaseError(
                f"support-card-{master_id} has no character band evidence"
            )
        band_ids = set()
        for character_id in character_ids:
            character = characters_by_master_id.get(character_id)
            if character is None:
                raise GameDatabaseError(
                    f"support-card-{master_id} references missing character "
                    f"{character_id}"
                )
            band_id = character.get("_bandID")
            if not isinstance(band_id, int):
                raise GameDatabaseError(
                    f"character {character_id} has invalid band {band_id!r}"
                )
            band_ids.add(band_id)
        if len(band_ids) != 1:
            warnings.append(
                f"support-card-{master_id} spans bands {sorted(band_ids)}; "
                "rank material and growth remain unresolved"
            )
            continue
        band_id = next(iter(band_ids))
        band = bands_by_master_id.get(band_id)
        if band is None:
            raise GameDatabaseError(
                f"support-card-{master_id} references missing band {band_id}"
            )
        rarity = int(row.get("_rarity") or 0)
        item_field = SUPPORT_RANK_ITEM_FIELDS.get(rarity)
        if item_field is None:
            raise GameDatabaseError(
                f"support-card-{master_id} has unsupported rarity {rarity}"
            )
        rank_item_master_id = int(band.get(item_field) or 0)
        if not rank_item_master_id:
            raise GameDatabaseError(
                f"support-card-{master_id} band {band_id} has no "
                f"rank material for rarity {rarity}"
            )
        key = (
            level_group,
            rank_group,
            rarity,
            rank_item_master_id,
        )
        support_cards_by_key[key].append(f"support-card-{master_id}")

    profiles = []
    card_growth: dict[str, dict[str, Any]] = {}

    for key, card_ids in sorted(member_cards_by_key.items()):
        (
            level_group,
            rank_group,
            awake_group,
            awake_resource_group,
            rarity,
            rank_item_master_id,
        ) = key
        level_rows = _require_group(
            member_levels,
            level_group,
            "member level",
        )
        rank_rows = _require_group(
            member_ranks,
            rank_group,
            "member rank",
        )
        awake_rows = _require_group(
            member_awakes,
            awake_group,
            "member awake",
        )
        awake_resource_rows = _require_group(
            member_awake_resources,
            awake_resource_group,
            "member awake resource",
        )
        if rank_item_master_id and rank_item_master_id not in items_by_master_id:
            raise GameDatabaseError(
                f"member growth references missing item "
                f"{rank_item_master_id}"
            )
        profile_id = (
            f"member-growth-l{level_group}-r{rank_group}-"
            f"a{awake_group}-ar{awake_resource_group}-"
            f"rarity{rarity}-item{rank_item_master_id}"
        )
        requirements = []
        for row in sorted(rank_rows, key=lambda value: value["_rank"]):
            amount = int(row.get("_requiredRankUpItemCount") or 0)
            if amount and rank_item_master_id:
                requirements.append(
                    _material_requirement(
                        rank_item_master_id,
                        amount,
                        "member_rank",
                        int(row["_rank"]),
                        profile_id,
                        rank_group,
                        card_ids,
                    )
                )
        for row in sorted(
            awake_resource_rows,
            key=lambda value: (
                value["_awakeCount"],
                value["_itemId"],
            ),
        ):
            item_master_id = int(row["_itemId"])
            if item_master_id not in items_by_master_id:
                raise GameDatabaseError(
                    f"member awake group {awake_resource_group} references "
                    f"missing item {item_master_id}"
                )
            requirements.append(
                _material_requirement(
                    item_master_id,
                    int(row.get("_count") or 0),
                    "member_awake",
                    int(row["_awakeCount"]),
                    profile_id,
                    awake_resource_group,
                    card_ids,
                )
            )
        level_limits = [
            {
                "awakeCount": int(row["_awakeCount"]),
                "limitLevel": int(row["_limitLevel"]),
            }
            for row in sorted(
                limits_by_rarity.get(rarity, []),
                key=lambda value: value["_awakeCount"],
            )
        ]
        level_curve = [
            {
                "level": int(row["_level"]),
                "rawExp": int(row.get("_exp") or 0),
                "rates": _rates(row),
            }
            for row in sorted(level_rows, key=lambda value: value["_level"])
        ]
        ranks = [
            {
                "rank": int(row["_rank"]),
                "requiredRankUpItemCount": int(
                    row.get("_requiredRankUpItemCount") or 0
                ),
                "rates": _rates(row),
                "leaderSkillLevel": int(
                    row.get("_leaderSkillLevel") or 0
                ),
                "musicTypeBonusRate": int(
                    row.get("_musicTypeBonusRate") or 0
                ),
                "musicTagBonusRate": int(
                    row.get("_musicTagBonusRate") or 0
                ),
            }
            for row in sorted(rank_rows, key=lambda value: value["_rank"])
        ]
        awakes = [
            {
                "awakeCount": int(row["_awakeCount"]),
                "rates": _rates(row),
            }
            for row in sorted(
                awake_rows,
                key=lambda value: value["_awakeCount"],
            )
        ]
        max_level = max(
            [entry["limitLevel"] for entry in level_limits]
            or [entry["level"] for entry in level_curve]
            or [0]
        )
        profile = {
            "id": profile_id,
            "cardKind": "member",
            "levelGroup": level_group,
            "rankGroup": rank_group,
            "awakeGroup": awake_group,
            "awakeResourceGroup": awake_resource_group,
            "rarity": rarity,
            "rankItemId": (
                f"item-{rank_item_master_id}"
                if rank_item_master_id
                else None
            ),
            "levelCurve": level_curve,
            "levelLimits": level_limits,
            "ranks": ranks,
            "awakes": awakes,
            "materialRequirements": requirements,
            "sourceCardIds": sorted(card_ids),
        }
        profiles.append(profile)
        for card_id in card_ids:
            card_growth[card_id] = {
                "profile": profile,
                "summary": {
                    "maxLevel": max_level,
                    "maxRank": max(
                        [entry["rank"] for entry in ranks] or [0]
                    ),
                    "maxAwake": max(
                        [entry["awakeCount"] for entry in awakes] or [0]
                    ),
                },
            }

    for key, card_ids in sorted(support_cards_by_key.items()):
        level_group, rank_group, rarity, rank_item_master_id = key
        level_rows = _require_group(
            support_levels,
            level_group,
            "support level",
        )
        rank_rows = _require_group(
            support_ranks,
            rank_group,
            "support rank",
        )
        if rank_item_master_id and rank_item_master_id not in items_by_master_id:
            raise GameDatabaseError(
                f"support growth references missing item "
                f"{rank_item_master_id}"
            )
        profile_id = (
            f"support-growth-l{level_group}-r{rank_group}-"
            f"rarity{rarity}-item{rank_item_master_id}"
        )
        requirements = []
        for row in sorted(rank_rows, key=lambda value: value["_rank"]):
            amount = int(row.get("_requiredRankUpItemCount") or 0)
            if amount and rank_item_master_id:
                requirements.append(
                    _material_requirement(
                        rank_item_master_id,
                        amount,
                        "support_rank",
                        int(row["_rank"]),
                        profile_id,
                        rank_group,
                        card_ids,
                    )
                )
        level_curve = [
            {
                "level": int(row["_level"]),
                "rawExp": int(row.get("_exp") or 0),
                "rates": _rates(row),
            }
            for row in sorted(level_rows, key=lambda value: value["_level"])
        ]
        ranks = [
            {
                "rank": int(row["_rank"]),
                "limitLevel": int(row.get("_limitLevel") or 0),
                "requiredRankUpItemCount": int(
                    row.get("_requiredRankUpItemCount") or 0
                ),
                "supportSkillLevel": int(
                    row.get("_supportSkillLevel") or 0
                ),
                "gekisouSupportSkillLevel": int(
                    row.get("_gekisouSupportSkillLevel") or 0
                ),
                "supportSkill01Level": int(
                    row.get("_supportSkill01Level") or 0
                ),
                "supportSkill02Level": int(
                    row.get("_supportSkill02Level") or 0
                ),
                "gekisouSupportSkill01Level": int(
                    row.get("_gekisouSupportSkill01Level") or 0
                ),
                "gekisouSupportSkill02Level": int(
                    row.get("_gekisouSupportSkill02Level") or 0
                ),
                "cardTypeLinkBonusRate": int(
                    row.get("_cardTypeLinkBonusRate") or 0
                ),
            }
            for row in sorted(rank_rows, key=lambda value: value["_rank"])
        ]
        max_level = max(
            [entry["limitLevel"] for entry in ranks]
            or [entry["level"] for entry in level_curve]
            or [0]
        )
        profile = {
            "id": profile_id,
            "cardKind": "support",
            "levelGroup": level_group,
            "rankGroup": rank_group,
            "awakeGroup": None,
            "awakeResourceGroup": None,
            "rarity": rarity,
            "rankItemId": (
                f"item-{rank_item_master_id}"
                if rank_item_master_id
                else None
            ),
            "levelCurve": level_curve,
            "levelLimits": [],
            "ranks": ranks,
            "awakes": [],
            "materialRequirements": requirements,
            "sourceCardIds": sorted(card_ids),
        }
        profiles.append(profile)
        for card_id in card_ids:
            card_growth[card_id] = {
                "profile": profile,
                "summary": {
                    "maxLevel": max_level,
                    "maxRank": max(
                        [entry["rank"] for entry in ranks] or [0]
                    ),
                    "maxAwake": 0,
                },
            }

    for profile in profiles:
        for requirement in profile["materialRequirements"]:
            item_master_id = int(requirement["itemId"].split("-", 1)[1])
            items_by_master_id[item_master_id]["usages"].append(requirement)
    return profiles, card_growth, warnings


def _build_skill_resource_profiles(
    tables: Mapping[str, list[dict[str, Any]]],
    items_by_master_id: Mapping[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    grouped = _rows_by_group(tables["MasterSkillLevelResource"])
    profiles: dict[int, dict[str, Any]] = {}
    for group_id, rows in sorted(grouped.items()):
        requirements = []
        for row in sorted(
            rows,
            key=lambda value: (value["_level"], value["_itemID"]),
        ):
            item_master_id = int(row["_itemID"])
            if item_master_id not in items_by_master_id:
                raise GameDatabaseError(
                    f"skill resource group {group_id} references missing "
                    f"item {item_master_id}"
                )
            requirements.append(
                _material_requirement(
                    item_master_id,
                    int(row.get("_count") or 0),
                    "skill_level",
                    int(row["_level"]),
                    f"skill-resource-group-{group_id}",
                    group_id,
                    [],
                )
            )
        profiles[group_id] = {
            "id": f"skill-resource-group-{group_id}",
            "groupId": group_id,
            "materialRequirements": requirements,
            "relatedSkillIds": [],
            "sourceCardIds": [],
        }
    return profiles


def _attach_skill_resource_profiles(
    card_projections: dict[str, Any],
    profiles: Mapping[int, dict[str, Any]],
    items_by_master_id: Mapping[int, dict[str, Any]],
) -> None:
    for projection in [
        *card_projections["memberCards"],
        *card_projections["supportCards"],
    ]:
        for skill_ref in projection["skillRefs"]:
            group_id = int(skill_ref.get("levelResourceGroup") or 0)
            if not group_id:
                continue
            profile = profiles.get(group_id)
            if not profile:
                raise GameDatabaseError(
                    f"{projection['cardId']} references missing skill "
                    f"resource group {group_id}"
                )
            if projection["cardId"] not in profile["sourceCardIds"]:
                profile["sourceCardIds"].append(projection["cardId"])
            if skill_ref["skillId"] not in profile["relatedSkillIds"]:
                profile["relatedSkillIds"].append(skill_ref["skillId"])
            skill_ref["materialRequirements"] = profile[
                "materialRequirements"
            ]
            projection["materialSummary"].extend(
                profile["materialRequirements"]
            )

    for profile in profiles.values():
        profile["sourceCardIds"].sort()
        profile["relatedSkillIds"].sort()
        for requirement in profile["materialRequirements"]:
            requirement["cardIds"] = list(profile["sourceCardIds"])
            item_master_id = int(requirement["itemId"].split("-", 1)[1])
            items_by_master_id[item_master_id]["usages"].append(requirement)


def _build_card_projections(
    tables: Mapping[str, list[dict[str, Any]]],
    skills: list[dict[str, Any]],
    card_growth: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    skills_by_id = {skill["id"]: skill for skill in skills}
    member_projections = []
    support_projections = []

    for row in sorted(tables["MasterMemberCard"], key=lambda value: value["_id"]):
        master_id = int(row["_id"])
        refs = [
            _skill_ref(
                "leader",
                "leader",
                row.get("_leaderSkillID"),
            ),
            _skill_ref(
                "live",
                "live",
                row.get("_liveSkillID"),
                row.get("_liveSkillLevelResourceGroup"),
            ),
            _skill_ref(
                "gekisou",
                "gekisou",
                row.get("_gekisouSkillID"),
                row.get("_gekisouSkillLevelResourceGroup"),
            ),
        ]
        refs = [ref for ref in refs if ref]
        card_id = f"member-card-{master_id}"
        growth = card_growth.get(card_id)
        member_projections.append(
            {
                "cardId": card_id,
                "cardKind": "member",
                "skillRefs": refs,
                "growthProfileId": (
                    growth["profile"]["id"] if growth else None
                ),
                "skillSummaries": [],
                "growthSummary": growth["summary"] if growth else {},
                "materialSummary": (
                    list(growth["profile"]["materialRequirements"])
                    if growth
                    else []
                ),
                "projectionStatus": "identified",
            }
        )

    for row in sorted(
        tables["MasterSupportCard"],
        key=lambda value: value["_id"],
    ):
        master_id = int(row["_id"])
        refs = [
            _skill_ref(
                "support_1",
                "support",
                row.get("_supportSkillId01"),
            ),
            _skill_ref(
                "support_2",
                "support",
                row.get("_supportSkillId02"),
            ),
            _skill_ref(
                "gekisou_support_1",
                "gekisou_support",
                row.get("_gekisouSupportSkillId01"),
            ),
            _skill_ref(
                "gekisou_support_2",
                "gekisou_support",
                row.get("_gekisouSupportSkillId02"),
            ),
        ]
        refs = [ref for ref in refs if ref]
        card_id = f"support-card-{master_id}"
        growth = card_growth.get(card_id)
        support_projections.append(
            {
                "cardId": card_id,
                "cardKind": "support",
                "skillRefs": refs,
                "growthProfileId": (
                    growth["profile"]["id"] if growth else None
                ),
                "skillSummaries": [],
                "growthSummary": growth["summary"] if growth else {},
                "materialSummary": (
                    list(growth["profile"]["materialRequirements"])
                    if growth
                    else []
                ),
                "projectionStatus": (
                    "partial"
                    if growth is None
                    and (row.get("_supportCardLevelGroup") or row.get("_supportCardRankGroup"))
                    else "identified"
                ),
            }
        )

    for projection in [*member_projections, *support_projections]:
        for ref in projection["skillRefs"]:
            skill = skills_by_id.get(ref["skillId"])
            if not skill:
                raise GameDatabaseError(
                    f"{projection['cardId']} references missing skill "
                    f"{ref['skillId']}"
                )
            skill["relatedCardIds"].append(projection["cardId"])
            levels = skill["levels"]
            projection["skillSummaries"].append(
                {
                    "slot": ref["slot"],
                    "skillId": skill["id"],
                    "name": skill["name"],
                    "level": levels[-1]["level"] if levels else 0,
                    "summary": (
                        levels[-1]["renderedSummary"] if levels else ""
                    ),
                    "interpretationStatus": skill["interpretationStatus"],
                }
            )
            if skill["interpretationStatus"] != "identified":
                projection["projectionStatus"] = "partial"
    return {
        "schemaVersion": 1,
        "memberCards": member_projections,
        "supportCards": support_projections,
    }


def build_game_database(
    master_root: Path,
    release_id: str,
    icon_asset_ids: Mapping[str, str] | None = None,
) -> GameDatabaseBuild:
    """Build normalized data and card projections from one Master release."""

    tables = {
        name: _load_table(master_root, name) for name in REQUIRED_TABLES
    }
    texts = _unique_index(
        tables["MasterText"],
        "_id",
        "text",
        str,
    )
    icons = dict(icon_asset_ids or {})
    targets = [
        _normalize_target(row)
        for row in sorted(
            tables["MasterSkillTarget"],
            key=lambda value: value["_id"],
        )
    ]
    target_master_ids = {
        int(row["_id"]) for row in tables["MasterSkillTarget"]
    }
    (
        conditions,
        condition_groups,
        cumulative_conditions,
        condition_warnings,
    ) = _build_conditions(
        tables,
        target_master_ids,
        _referenced_condition_group_ids(tables),
    )
    skills, skill_warnings = _build_skills(
        tables,
        texts,
        icons,
        {group["groupId"] for group in condition_groups},
        {
            condition["masterId"]
            for condition in cumulative_conditions
        },
    )
    warnings = [*condition_warnings, *skill_warnings]
    for row in tables["MasterMemberCard"]:
        link_group = int(row.get("_linkSkillLevelResourceGroup") or 0)
        if link_group:
            warnings.append(
                f"member-card-{int(row['_id'])} preserves unresolved "
                f"link skill resource group {link_group}"
            )
    for skill in skills:
        skill["sourceReleaseIds"] = [release_id]
    items, items_by_master_id = _build_items(
        tables,
        texts,
        icons,
        release_id,
    )
    from tools.item_acquisition import build_item_acquisition, build_live_item_drops

    acquisition = build_item_acquisition(master_root)
    live_drops = build_live_item_drops(master_root)
    for item in items:
        item["acquisitionSources"] = acquisition.get(item["id"], [])
        item["liveDrops"] = live_drops.get(item["id"], [])

    growth_profiles, card_growth, growth_warnings = _build_growth_profiles(
        tables,
        items_by_master_id,
    )
    warnings.extend(growth_warnings)
    skill_resource_profiles = _build_skill_resource_profiles(
        tables,
        items_by_master_id,
    )
    card_projections = _build_card_projections(
        tables,
        skills,
        card_growth,
    )
    _attach_skill_resource_profiles(
        card_projections,
        skill_resource_profiles,
        items_by_master_id,
    )
    for skill in skills:
        if skill.get("iconAssetId"):
            skill["iconStatus"] = "identified"
            skill["iconEvidence"] = "master_icon_asset_relation"
        else:
            skill["iconStatus"] = "source_missing"
            skill["iconEvidence"] = (
                "MasterSkillIcon normal asset name has no extracted asset"
            )
        if skill["relatedCardIds"]:
            skill["publicationStatus"] = "public"
            skill["publicationReason"] = "referenced_by_public_card"
        else:
            skill["publicationStatus"] = "archive_only"
            skill["publicationReason"] = "unreferenced_skill"
    database = {
            "schemaVersion": 1,
            "sourceReleaseId": release_id,
            "skills": skills,
            "conditions": conditions,
            "conditionGroups": condition_groups,
            "cumulativeConditions": cumulative_conditions,
            "targets": targets,
            "growthProfiles": growth_profiles,
            "skillLevelResourceProfiles": list(
                skill_resource_profiles.values()
            ),
            "items": items,
            "quality": {
                "skillCount": len(skills),
                "itemCount": len(items),
                "growthProfileCount": len(growth_profiles),
                "partialSkillCount": sum(
                    skill["interpretationStatus"] != "identified"
                    for skill in skills
                ),
                "publicSkillCount": sum(
                    skill["publicationStatus"] == "public"
                    for skill in skills
                ),
                "archivedSkillCount": sum(
                    skill["publicationStatus"] == "archive_only"
                    for skill in skills
                ),
                "missingSkillIconCount": sum(
                    skill["iconStatus"] == "source_missing"
                    for skill in skills
                ),
                "unexplainedMissingSkillIconCount": sum(
                    skill.get("iconAssetId") is None
                    and skill.get("iconStatus") != "source_missing"
                    for skill in skills
                ),
            },
        }
    return GameDatabaseBuild(
        database=database,
        card_projections=card_projections,
        warnings=warnings,
    )
