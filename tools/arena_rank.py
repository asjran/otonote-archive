"""Build a conservative Arena Rank capability and season projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArenaRankError(ValueError):
    """Raised when reviewed Arena evidence is incomplete or malformed."""


MASTER_TABLES = (
    "MasterText",
    "MasterLiveGekisouMatchingBucket",
    "MasterLiveGekisouRankingScoreBonus",
)

REQUIRED_CLIENT_SYMBOLS = (
    "ArenaPlay",
    "ArenaRank",
    "GekisouArena",
    "GekisouArenaRank",
)

REQUIRED_RESOURCES = (
    "Btn_GekisoArena",
    "BattleLiveArenaPenLight",
)

BASE_SEASON_FIELDS = (
    "seasonId",
    "startAt",
    "endAt",
    "status",
    "sourceReleaseId",
)

MISSING_SEASON_FIELDS = (
    *BASE_SEASON_FIELDS[:-1],
    "leaderboardStatus",
    "rewardDefinitions",
    BASE_SEASON_FIELDS[-1],
)

CAPABILITIES = (
    ("rating", "Rating", "client"),
    ("league-points", "联赛点", "client"),
    ("master-points", "大师点与大师段位", "client"),
    ("winning-streak", "连胜", "master-text"),
    ("season-lifecycle", "赛季开始、结束与结算", "client"),
    ("rankings", "当前与上赛季排行榜", "master-text"),
    ("reward-groups", "Ranking、Promotion、Season 奖励", "master-text"),
    ("daily-reward", "每日奖励", "master-text"),
    ("season-pass", "赛季通行证", "master-text"),
    ("exchange", "Arena 兑换入口", "master-text"),
    ("formation-suitability", "编队适性", "master-text"),
    ("support-items", "支援道具", "master-text"),
    ("trends", "流行度与编成趋势", "master-text"),
    ("matching-timeout", "匹配超时", "master-text"),
    ("disconnect-penalty", "断线惩罚", "master-text"),
)


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise ArenaRankError(f"missing Arena evidence: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArenaRankError(f"invalid JSON in {path}: {exc}") from exc


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    payload = _load_json(root / f"{name}.json")
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ArenaRankError(f"{name} must contain an _allData array")
    return rows


def _validate_reviewed_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ArenaRankError("Arena client evidence must use schemaVersion 1")
    symbols = payload.get("clientSymbols")
    if not isinstance(symbols, list) or any(
        symbol not in symbols for symbol in REQUIRED_CLIENT_SYMBOLS
    ):
        raise ArenaRankError("Arena clientSymbols are incomplete")
    resources = payload.get("resources")
    if not isinstance(resources, list) or any(
        resource not in resources for resource in REQUIRED_RESOURCES
    ):
        raise ArenaRankError("Arena resources are incomplete")
    flags = payload.get("featureFlags")
    if not isinstance(flags, dict) or not isinstance(
        flags.get("CcEnableArenas"),
        bool,
    ):
        raise ArenaRankError("Arena featureFlags are incomplete")
    return payload


def _season_projection(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str], str]:
    if payload is None:
        return None, list(MISSING_SEASON_FIELDS), "server_unavailable"
    missing = [
        field
        for field in BASE_SEASON_FIELDS
        if field not in payload or payload[field] is None
    ]
    if payload.get("leaderboard") is None and payload.get("leaderboardStatus") is None:
        missing.append("leaderboardStatus")
    reward_definitions = payload.get("rewardDefinitions")
    if not isinstance(reward_definitions, list) or not reward_definitions:
        missing.append("rewardDefinitions")
    if missing:
        return None, missing, "server_data_incomplete"
    return payload, [], "season_available"


def build_arena_rank(
    master_root: Path,
    release_id: str,
    reviewed_evidence_path: Path,
    *,
    season_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project confirmed client capability without inventing a live season."""
    tables = {name: _load_table(master_root, name) for name in MASTER_TABLES}
    reviewed = _validate_reviewed_evidence(_load_json(reviewed_evidence_path))
    arena_text_rows = [
        row
        for row in tables["MasterText"]
        if isinstance(row.get("_id"), str)
        and (
            "Arena" in row["_id"]
            or "arena" in row["_id"]
            or row["_id"].startswith("Mission_Description_Arena")
        )
    ]
    if not any(
        row.get("_id") == "Mission_Description_ArenaPlay"
        for row in arena_text_rows
    ):
        raise ArenaRankError("MasterText lacks the Arena Rank Match evidence")
    current_season, missing_fields, status = _season_projection(season_payload)
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "status": status,
        "capabilities": [
            {
                "id": capability_id,
                "label": label,
                "sourceLevel": source_level,
                "status": "structure_confirmed",
            }
            for capability_id, label, source_level in CAPABILITIES
        ],
        "relationships": [
            {
                "id": "gekisou",
                "statement": "当前版本与撃奏高度关联",
                "detail": "客户端命名、入口、玩家档案字段与编队适性均指向撃奏，但证据不足以定义为永久独占关系。",
                "sourceLevel": "client",
            },
            {
                "id": "battle-live",
                "statement": "复用部分 Battle Live 运行资源",
                "detail": "资源证据包含 BattleLiveArenaPenLight。",
                "sourceLevel": "resource",
            },
            {
                "id": "season-service",
                "statement": "实际段位与排行榜依赖赛季服务",
                "detail": "当前发布版本没有完整的赛季、榜单、阈值或奖励实例。",
                "sourceLevel": "server-missing",
            },
        ],
        "evidence": {
            "featureFlags": reviewed["featureFlags"],
            "clientSymbols": reviewed["clientSymbols"],
            "resources": reviewed["resources"],
            "masterTables": [
                {
                    "table": name,
                    "rowCount": len(tables[name]),
                }
                for name in MASTER_TABLES
            ],
            "arenaTextRowCount": len(arena_text_rows),
        },
        "currentSeason": current_season,
        "pastSeasons": [],
        "missingServerFields": missing_fields,
    }
