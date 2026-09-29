"""Build the High Score Rating target-planning projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HighScoreRatingError(ValueError):
    """Raised when rating thresholds cannot be published without guessing."""


TABLES = (
    "MasterParameter",
    "MasterLiveTotalHighScoreRating",
    "MasterLiveBandHighScoreRating",
    "MasterReward",
    "MasterItem",
    "MasterText",
)

GRADE_NAMES = ("Bronze", "Silver", "Gold")
STEP_NAMES = ("", "I", "II", "III", "IV", "V")


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise HighScoreRatingError(f"missing Master table: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HighScoreRatingError(f"invalid JSON in {path}: {exc}") from exc
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise HighScoreRatingError(f"{name} must contain an _allData array")
    return rows


def _text_value(row: dict[str, Any]) -> str:
    for key in (
        "_simplifiedChinese",
        "_traditionalChinese",
        "_english",
        "_japanese",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_levels(
    rows: list[dict[str, Any]],
    scope: str,
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    previous_rating: int | None = None
    for row in rows:
        grade = row.get("_grade")
        step = row.get("_step")
        rating = row.get("_rating")
        if (
            not isinstance(grade, int)
            or not 0 <= grade < len(GRADE_NAMES)
            or not isinstance(step, int)
            or not 0 <= step < len(STEP_NAMES)
            or not isinstance(rating, int)
            or rating < 0
        ):
            raise HighScoreRatingError(
                f"{scope} rating level contains an invalid grade, step, or rating"
            )
        key = (grade, step)
        if key in seen:
            raise HighScoreRatingError(
                f"{scope} rating levels contain duplicate grade/step {key}"
            )
        if previous_rating is not None and rating <= previous_rating:
            raise HighScoreRatingError(
                f"{scope} rating thresholds must be strictly increasing"
            )
        reward_ids = row.get("_liveMusicRewardIds", [])
        if not isinstance(reward_ids, list) or not all(
            isinstance(reward_id, int) for reward_id in reward_ids
        ):
            raise HighScoreRatingError(
                f"{scope} rating level {key} has invalid reward references"
            )
        suffix = STEP_NAMES[step]
        levels.append(
            {
                "id": f"{grade}-{step}",
                "grade": grade,
                "step": step,
                "label": f"{GRADE_NAMES[grade]}{f' {suffix}' if suffix else ''}",
                "rating": rating,
                "rewardIds": reward_ids,
            }
        )
        seen.add(key)
        previous_rating = rating
    if not levels:
        raise HighScoreRatingError(f"{scope} rating levels are empty")
    return levels


def _resolve_rewards(
    reward_rows: list[dict[str, Any]],
    item_rows: list[dict[str, Any]],
    text_rows: list[dict[str, Any]],
    referenced_ids: set[int],
) -> tuple[dict[str, dict[str, Any]], list[int]]:
    rewards = {
        row.get("_id"): row
        for row in reward_rows
        if isinstance(row.get("_id"), int)
    }
    items = {
        row.get("_id"): row
        for row in item_rows
        if isinstance(row.get("_id"), int)
    }
    texts = {
        row.get("_id"): _text_value(row)
        for row in text_rows
        if isinstance(row.get("_id"), str)
    }
    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[int] = []
    for reward_id in sorted(referenced_ids):
        reward = rewards.get(reward_id)
        if reward is None:
            unresolved.append(reward_id)
            continue
        resource_id = reward.get("_resourceId")
        item = items.get(resource_id) if isinstance(resource_id, int) else None
        name_text_id = item.get("_nameTextId") if item else None
        name = texts.get(name_text_id, "") if isinstance(name_text_id, str) else ""
        resolved[str(reward_id)] = {
            "id": reward_id,
            "resourceType": reward.get("_resourceType"),
            "resourceId": resource_id,
            "count": reward.get("_resourceCount"),
            "name": name or f"Resource {resource_id}",
        }
    return resolved, unresolved


def build_high_score_rating(
    master_root: Path,
    release_id: str,
) -> dict[str, Any]:
    """Normalize the two rating tracks and their referenced rewards."""
    tables = {name: _load_table(master_root, name) for name in TABLES}
    parameters = {
        row.get("_id"): row.get("_value")
        for row in tables["MasterParameter"]
    }
    raw_top_count = parameters.get("high_score_rating_top_music_count")
    try:
        top_music_count = int(str(raw_top_count))
    except (TypeError, ValueError) as exc:
        raise HighScoreRatingError(
            "high_score_rating_top_music_count must be a positive integer"
        ) from exc
    if top_music_count <= 0:
        raise HighScoreRatingError(
            "high_score_rating_top_music_count must be a positive integer"
        )

    total_levels = _normalize_levels(
        tables["MasterLiveTotalHighScoreRating"],
        "total",
    )
    band_rows = tables["MasterLiveBandHighScoreRating"]
    invalid_band_ids = {
        row.get("_bandId")
        for row in band_rows
        if row.get("_bandId") != 0
    }
    if invalid_band_ids:
        raise HighScoreRatingError(
            "band rating projection currently requires common _bandId 0 thresholds"
        )
    band_levels = _normalize_levels(band_rows, "band")
    referenced_ids = {
        reward_id
        for level in (*total_levels, *band_levels)
        for reward_id in level["rewardIds"]
    }
    resolved_rewards, unresolved_reward_ids = _resolve_rewards(
        tables["MasterReward"],
        tables["MasterItem"],
        tables["MasterText"],
        referenced_ids,
    )
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "topMusicCount": top_music_count,
        "scopes": {
            "total": {
                "label": "总合 Rating",
                "levelCount": len(total_levels),
                "levels": total_levels,
            },
            "band": {
                "label": "乐队 Rating",
                "levelCount": len(band_levels),
                "levels": band_levels,
            },
        },
        "resolvedRewards": resolved_rewards,
        "unresolvedRewardIds": unresolved_reward_ids,
        "evidence": [
            {
                "table": name,
                "rowCount": len(tables[name]),
            }
            for name in TABLES
        ],
    }
