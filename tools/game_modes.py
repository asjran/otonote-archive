"""Build evidence-backed game mode archives and the event publication gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class GameModeError(ValueError):
    """Raised when mode evidence cannot be read without guessing."""


MODE_TABLES = {
    "battle-live": (
        "MasterBattleLiveReward",
        "MasterLiveScoreRank",
    ),
    "gekisou": (
        "MasterGekisouLiveRankReward",
        "MasterGekisouSkill",
        "MasterGekisouSkillEffect",
        "MasterGekisouSupportSkill",
        "MasterGekisouSupportSkillEffect",
        "MasterLiveGekisouMatchingBucket",
        "MasterLiveGekisouRankingScoreBonus",
    ),
}

EVENT_TABLES = (
    "MasterEvent",
    "MasterEventAchievementReward",
    "MasterEventRankingReward",
    "MasterEventEffect",
    "MasterEventPickUpCard",
    "MasterEventBoxGacha",
    "MasterEventBoxGachaReward",
)

REQUIRED_TABLES = tuple(
    dict.fromkeys(
        table
        for tables in (*MODE_TABLES.values(), EVENT_TABLES)
        for table in tables
    )
)


def empty_game_modes(release_id: str, status: str) -> dict[str, Any]:
    """Return an explicit unavailable projection for reduced test/asset builds."""
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "modes": [],
        "events": {
            "definitionCount": 0,
            "instanceRoutesEnabled": False,
            "orphanAuxiliaryRowCount": 0,
            "capabilities": {
                "hasStory": False,
                "hasMode": False,
                "hasRewards": False,
                "hasRanking": False,
            },
            "evidence": [],
            "status": status,
        },
    }


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise GameModeError(f"missing Master table: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GameModeError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise GameModeError(f"{name} must contain an _allData array")
    return rows


def _distinct_int_count(rows: Iterable[dict[str, Any]], field: str) -> int:
    return len({row[field] for row in rows if isinstance(row.get(field), int)})


def _evidence(tables: dict[str, list[dict[str, Any]]], names: Iterable[str]) -> list[dict[str, Any]]:
    return [
        {"table": name, "rowCount": len(tables[name])}
        for name in names
    ]


def _reward_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "rowCount": len(rows),
        "groupCount": _distinct_int_count(rows, "_group"),
        "rankCount": _distinct_int_count(rows, "_liveScoreRank"),
    }


def _mode(
    *,
    mode_id: str,
    name: str,
    master_name: str,
    aliases: list[str],
    description: str,
    evidence: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    reward_summary: dict[str, int],
    auto_demo: bool,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "id": mode_id,
        "name": name,
        "masterName": master_name,
        "aliases": aliases,
        "description": description,
        "status": "archive_available",
        "capabilities": {
            "archive": True,
            "autoDemo": auto_demo,
            "offlineSimulation": False,
            "onlineMultiplayer": False,
        },
        "metrics": metrics,
        "rewardSummary": reward_summary,
        "evidence": evidence,
        "evidenceRowCount": sum(item["rowCount"] for item in evidence),
        "blockers": blockers,
    }


def build_game_modes(master_root: Path, release_id: str) -> dict[str, Any]:
    """Build mode and event capability records from one immutable release."""
    tables = {name: _load_table(master_root, name) for name in REQUIRED_TABLES}

    battle_evidence = _evidence(tables, MODE_TABLES["battle-live"])
    gekisou_evidence = _evidence(tables, MODE_TABLES["gekisou"])

    modes = [
        _mode(
            mode_id="battle-live",
            name="Battle Live",
            master_name="BattleLive",
            aliases=["多人演奏资料"],
            description="Battle Live 奖励与分数门槛的只读档案；不包含房间、匹配或实时对战。",
            evidence=battle_evidence,
            metrics=[
                {"label": "奖励记录", "value": len(tables["MasterBattleLiveReward"])},
                {"label": "共享分数档位记录", "value": len(tables["MasterLiveScoreRank"])},
            ],
            reward_summary=_reward_summary(tables["MasterBattleLiveReward"]),
            auto_demo=False,
            blockers=[
                "队伍构成、模式修正和结果结算仍需正式样本验证。",
                "真实联机不属于当前站点范围。",
            ],
        ),
        _mode(
            mode_id="gekisou",
            name="撃奏",
            master_name="Gekisou",
            aliases=["Gekisou", "激奏"],
            description="撃奏技能、支援、排位奖励、匹配分桶与排名加成的证据档案。",
            evidence=gekisou_evidence,
            metrics=[
                {"label": "撃奏技能", "value": len(tables["MasterGekisouSkill"])},
                {"label": "撃奏支援", "value": len(tables["MasterGekisouSupportSkill"])},
                {"label": "排位奖励", "value": len(tables["MasterGekisouLiveRankReward"])},
                {"label": "匹配分桶", "value": len(tables["MasterLiveGekisouMatchingBucket"])},
                {"label": "排名加成", "value": len(tables["MasterLiveGekisouRankingScoreBonus"])},
            ],
            reward_summary=_reward_summary(tables["MasterGekisouLiveRankReward"]),
            auto_demo=False,
            blockers=[
                "“Just 激奏”称呼、触发语义、匹配和计分修正仍需客户端证据。",
                "真实联机不属于当前站点范围。",
            ],
        ),
    ]

    event_evidence = _evidence(tables, EVENT_TABLES)
    definition_count = len(tables["MasterEvent"])
    auxiliary_count = sum(
        len(tables[name]) for name in EVENT_TABLES if name != "MasterEvent"
    )
    instance_routes_enabled = definition_count > 0
    events = {
        "definitionCount": definition_count,
        "instanceRoutesEnabled": instance_routes_enabled,
        "orphanAuxiliaryRowCount": 0 if instance_routes_enabled else auxiliary_count,
        "capabilities": {
            "hasStory": False,
            "hasMode": False,
            "hasRewards": False,
            "hasRanking": False,
        },
        "evidence": event_evidence,
        "status": "definitions_available" if instance_routes_enabled else "reserved_no_definitions",
    }

    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "modes": modes,
        "events": events,
    }
