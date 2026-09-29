"""Build verified music entities from decrypted Master tables and scores."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tools.resource_pipeline.localization import resolve_localized_text
from tools.music_score_runtime import (
    RuntimeScoreCompileError,
    compile_music_score,
)


DIFFICULTIES = (
    ("easy", "_easyID"),
    ("normal", "_normalID"),
    ("hard", "_hardID"),
    ("expert", "_expertID"),
)
DIFFICULTY_BY_CODE = {
    0: "easy",
    1: "normal",
    2: "hard",
    3: "expert",
}
COMBO_RATE_TYPES = frozenset({0, 1, 2, 3})
SCORE_CONTAINER = re.compile(
    r"^Assets/AddressableResources/Live/MusicScore/(?P<path>.+\.bytes)$"
)


class MusicCatalogError(ValueError):
    """Raised when required music data or relationships are invalid."""


@dataclass(frozen=True)
class MusicCatalogResult:
    tracks: list[dict[str, Any]]
    charts: list[dict[str, Any]]
    chart_data: dict[str, dict[str, Any]]
    warnings: list[str]


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise MusicCatalogError(f"missing Master table: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MusicCatalogError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MusicCatalogError(f"{name} must contain an _allData array")
    return rows


def _index(
    rows: list[dict[str, Any]],
    field: str,
    label: str,
) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field)
        if key in result:
            raise MusicCatalogError(f"duplicate {label} {field}: {key!r}")
        result[key] = row
    return result


def _text(texts: Mapping[str, dict[str, Any]], text_id: Any) -> str:
    if not isinstance(text_id, str) or not text_id:
        return ""
    row = texts.get(text_id)
    if not row:
        return ""
    return resolve_localized_text(row, "zh-CN").text


def _integer_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        raise MusicCatalogError(f"{label} must be an integer array")
    return value


def _store_payload(
    payloads: dict[str, bytes],
    logical_path: str,
    payload: bytes,
) -> None:
    if not payload:
        raise MusicCatalogError(f"music score {logical_path} is empty")
    existing = payloads.get(logical_path)
    if existing is not None and existing != payload:
        raise MusicCatalogError(
            f"music score {logical_path} has conflicting payloads"
        )
    payloads[logical_path] = payload


def collect_score_payloads(
    manifest: Mapping[str, Any],
    extracted_root: Path,
    bundle_root: Path,
) -> dict[str, bytes]:
    """Read all score TextAssets, preferring already exported binary files."""

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise MusicCatalogError("resource manifest must contain an assets array")

    payloads: dict[str, bytes] = {}
    pending_by_bundle: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for record in assets:
        if not isinstance(record, dict) or record.get("type") != "TextAsset":
            continue
        match = SCORE_CONTAINER.fullmatch(
            str(record.get("container_path") or "")
        )
        if not match:
            continue
        logical_path = match.group("path")
        exported_file = record.get("exported_file")
        if isinstance(exported_file, str):
            exported_path = extracted_root / exported_file
            if exported_path.is_file() and exported_path.stat().st_size:
                _store_payload(
                    payloads,
                    logical_path,
                    exported_path.read_bytes(),
                )
                continue
        bundle = record.get("bundle")
        path_id = record.get("path_id")
        if not isinstance(bundle, str) or not isinstance(path_id, int):
            raise MusicCatalogError(
                f"music score {logical_path} has no readable resource source"
            )
        pending_by_bundle[bundle].append((logical_path, path_id))

    if not pending_by_bundle:
        return payloads

    dependency_dir = Path(__file__).resolve().parents[1] / "analysis" / ".deps"
    if str(dependency_dir) not in sys.path:
        sys.path.insert(0, str(dependency_dir))
    try:
        import UnityPy  # type: ignore
    except ModuleNotFoundError as exc:
        raise MusicCatalogError(
            "UnityPy is required to recover non-exported music scores"
        ) from exc

    for bundle, pending in sorted(pending_by_bundle.items()):
        bundle_path = bundle_root / bundle
        if not bundle_path.is_file():
            raise MusicCatalogError(f"music score bundle is missing: {bundle_path}")
        environment = UnityPy.load(str(bundle_path))
        objects = {obj.path_id: obj for obj in environment.objects}
        for logical_path, path_id in pending:
            obj = objects.get(path_id)
            if obj is None:
                raise MusicCatalogError(
                    f"music score {logical_path} object {path_id} is missing"
                )
            data = obj.read()
            raw = getattr(data, "m_Script", getattr(data, "script", b""))
            payload = (
                raw.encode("utf-8", errors="surrogateescape")
                if isinstance(raw, str)
                else bytes(raw)
            )
            _store_payload(payloads, logical_path, payload)

    return payloads


def build_music_catalog(
    master_root: Path,
    score_payloads: Mapping[str, bytes],
    jacket_asset_ids: Mapping[str, str],
    release_id: str,
) -> MusicCatalogResult:
    """Build the entire music module through one deterministic interface."""

    music_rows = _load_table(master_root, "MasterLiveMusic")
    score_rows = _index(
        _load_table(master_root, "MasterLiveMusicScore"),
        "_id",
        "music score",
    )
    category_rows = _index(
        _load_table(master_root, "MasterLiveMusicCategory"),
        "_id",
        "music category",
    )
    score_rank_rows = _load_table(master_root, "MasterLiveScoreRank")
    score_reward_rows = _load_table(
        master_root,
        "MasterLiveMusicScoreReward",
    )
    combo_reward_rows = _load_table(
        master_root,
        "MasterLiveMusicComboReward",
    )
    tag_rows = _index(_load_table(master_root, "MasterTag"), "_id", "tag")
    band_rows = _index(_load_table(master_root, "MasterBand"), "_id", "band")
    character_rows = _index(
        _load_table(master_root, "MasterCharacter"),
        "_id",
        "character",
    )
    live_characters = _index(
        _load_table(master_root, "MasterLiveCharacter"),
        "_characterID",
        "live character",
    )
    texts = _index(_load_table(master_root, "MasterText"), "_id", "text")

    tracks: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    chart_data: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    seen_track_ids: set[int] = set()
    used_score_paths: set[str] = set()

    category_labels = {
        category_id: _text(texts, row.get("_textKey"))
        or f"分类 {category_id}"
        for category_id, row in category_rows.items()
    }
    tag_labels = {
        tag_id: _text(texts, row.get("_nameTextID")) or f"标签 {tag_id}"
        for tag_id, row in tag_rows.items()
    }
    score_ranks_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for score_rank in score_rank_rows:
        group_id = score_rank.get("_group")
        if isinstance(group_id, int) and not isinstance(group_id, bool):
            score_ranks_by_group[group_id].append(score_rank)
    score_rewards_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for reward in score_reward_rows:
        group_id = reward.get("_group")
        if isinstance(group_id, int) and not isinstance(group_id, bool):
            score_rewards_by_group[group_id].append(reward)
    combo_rewards_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for reward in combo_reward_rows:
        group_id = reward.get("_group")
        if isinstance(group_id, int) and not isinstance(group_id, bool):
            combo_rewards_by_group[group_id].append(reward)

    def reward_resource(
        reward: Mapping[str, Any],
        music_id: int,
        label: str,
    ) -> dict[str, int]:
        fields = ("_resourceType", "_resourceId", "_resourceCount")
        if any(
            not isinstance(reward.get(field), int)
            or isinstance(reward.get(field), bool)
            for field in fields
        ):
            raise MusicCatalogError(
                f"music {music_id} has invalid {label} resource"
            )
        return {
            "resourceType": int(reward["_resourceType"]),
            "resourceId": int(reward["_resourceId"]),
            "resourceCount": int(reward["_resourceCount"]),
        }

    gekisou_mission_types = {
        1: {"type": "combo", "label": "COMBO"},
        2: {"type": "luck", "label": "LUCK"},
        3: {"type": "just", "label": "JUST"},
    }

    def gekisou_missions(
        music: Mapping[str, Any],
        music_id: int,
    ) -> list[dict[str, Any]]:
        projected = []
        for index in range(1, 4):
            field = f"_gekisouMission{index}"
            type_code = music.get(field)
            mission_type = gekisou_mission_types.get(type_code)
            if mission_type is None:
                raise MusicCatalogError(
                    f"music {music_id} has unknown Gekisou mission "
                    f"{type_code!r} in {field}"
                )
            projected.append(
                {
                    "index": index,
                    "typeCode": int(type_code),
                    **mission_type,
                    "sourceField": field,
                    "evidenceStatus": "confirmed-data",
                }
            )
        return projected

    for row in sorted(music_rows, key=lambda item: int(item.get("_sortOrder", 0))):
        master_id = row.get("_id")
        if not isinstance(master_id, int) or isinstance(master_id, bool):
            raise MusicCatalogError(f"music has invalid _id: {master_id!r}")
        if master_id in seen_track_ids:
            raise MusicCatalogError(f"duplicate music _id: {master_id}")
        seen_track_ids.add(master_id)

        title = _text(texts, row.get("_titleTextID"))
        if not title:
            raise MusicCatalogError(f"music {master_id} is missing its title")

        band_ids = _integer_list(
            row.get("_bandIDs", []),
            f"music {master_id} band IDs",
        )
        vocalist_ids = _integer_list(
            row.get("_vocalCharacterIDs", []),
            f"music {master_id} vocalist IDs",
        )
        unknown_live_characters = [
            value for value in vocalist_ids if value not in live_characters
        ]
        if unknown_live_characters:
            raise MusicCatalogError(
                f"music {master_id} references missing live characters "
                f"{unknown_live_characters}"
            )

        band_labels = []
        unresolved_bands = []
        for band_id in band_ids:
            if band_id in band_rows:
                band_labels.append(
                    _text(texts, band_rows[band_id].get("_nameTextID"))
                    or tag_labels.get(band_id, f"乐队 ID {band_id}")
                )
            elif band_id in tag_labels:
                band_labels.append(tag_labels[band_id])
                unresolved_bands.append(band_id)
            else:
                raise MusicCatalogError(
                    f"music {master_id} references unknown band {band_id}"
                )

        vocalist_labels = []
        unresolved_vocalists = []
        for character_id in vocalist_ids:
            character = character_rows.get(character_id)
            if character:
                vocalist_labels.append(
                    _text(texts, character.get("_nameTextID"))
                    or f"角色 ID {character_id}"
                )
            else:
                vocalist_labels.append(f"角色 ID {character_id}")
                unresolved_vocalists.append(character_id)

        category_ids = _integer_list(
            row.get("_musicCategories", []),
            f"music {master_id} category IDs",
        )
        unknown_categories = [
            value for value in category_ids if value not in category_rows
        ]
        if unknown_categories:
            raise MusicCatalogError(
                f"music {master_id} references missing categories "
                f"{unknown_categories}"
            )
        tag_ids = _integer_list(
            row.get("_bestMusicTagIDs", []),
            f"music {master_id} tag IDs",
        )

        track_chart_ids = []
        track_charts = []
        for difficulty, field in DIFFICULTIES:
            score_id = row.get(field)
            if not isinstance(score_id, int) or score_id not in score_rows:
                raise MusicCatalogError(
                    f"music {master_id} has missing {difficulty} difficulty "
                    f"{score_id!r}"
                )
            score_row = score_rows[score_id]
            logical_name = score_row.get("_musicScoreTextFileName")
            if not isinstance(logical_name, str) or not logical_name:
                raise MusicCatalogError(
                    f"music score {score_id} is missing its logical path"
                )
            logical_path = f"{logical_name}.bytes"
            used_score_paths.add(logical_path)
            payload = score_payloads.get(logical_path)
            if not payload:
                raise MusicCatalogError(
                    f"music score {score_id} has no extracted payload at "
                    f"{logical_path}"
                )
            chart_id = f"music-chart-{score_id}"
            master_full_combo = score_row.get("_fullComboCount")
            if not isinstance(master_full_combo, int):
                raise MusicCatalogError(
                    f"music score {score_id} has invalid Full Combo count"
                )
            try:
                projection = compile_music_score(payload)
            except RuntimeScoreCompileError as exc:
                raise MusicCatalogError(
                    f"music score {score_id} could not be compiled: {exc}"
                ) from exc

            statistics = projection["statistics"]
            runtime_full_combo = statistics["runtimeFullCombo"]
            full_combo_delta = runtime_full_combo - master_full_combo
            full_combo_classification = (
                "MATCH"
                if full_combo_delta == 0
                else (
                    "RUNTIME_HIGHER"
                    if full_combo_delta > 0
                    else "RUNTIME_LOWER"
                )
            )
            chart = {
                "id": chart_id,
                "masterId": score_id,
                "trackId": f"music-{master_id}",
                "difficulty": difficulty,
                "level": int(score_row.get("_musicScoreLevel", 0)),
                "displayLevel": float(
                    score_row.get("_musicScoreDisplayLevel", 0)
                ),
                "fullComboCount": runtime_full_combo,
                "judgementCount": runtime_full_combo,
                "judgementCountSource": statistics["judgementCountSource"],
                "sourceJudgementCount": statistics["sourceJudgementCount"],
                "masterFullComboCount": master_full_combo,
                "fullComboDelta": full_combo_delta,
                "fullComboClassification": full_combo_classification,
                "fullComboStatus": (
                    "match" if full_combo_delta == 0 else "conflict"
                ),
                "runtimeAlgorithmVersion": projection["meta"][
                    "runtimeAlgorithmVersion"
                ],
                "explicitJudgementCount": statistics[
                    "explicitJudgementCount"
                ],
                "slideComboCandidateCount": statistics[
                    "slideComboCandidateCount"
                ],
                "skippedSlideComboCount": statistics[
                    "skippedSlideComboCount"
                ],
                "mergedEndpointReduction": statistics[
                    "mergedEndpointReduction"
                ],
                "guidePathCount": statistics["guidePathCount"],
                "autoControlNodeCount": statistics[
                    "autoControlNodeCount"
                ],
                "scoreLogicalPath": logical_path,
                "duration": projection["duration"],
                "bpm": statistics["bpm"],
                "noteCounts": statistics["noteCounts"],
                "averageDensity": statistics["averageDensity"],
                "peakDensity": statistics["peakDensity"],
                "skillCount": len(projection["skillTimings"]),
                "feverCount": len(projection["feverRanges"]),
                "analysisDataUrl": f"/data/music-charts/{chart_id}.json",
                "sourceReleaseIds": [release_id],
                "catalogStatus": "identified",
            }
            charts.append(chart)
            track_charts.append(chart)
            track_chart_ids.append(chart_id)
            chart_data[chart_id] = {
                "id": chart_id,
                "trackId": chart["trackId"],
                "difficulty": difficulty,
                **projection,
            }

        jacket_name = str(row.get("_jacketAssetName") or "")
        jacket_asset_id = jacket_asset_ids.get(jacket_name)
        if not jacket_asset_id:
            warnings.append(
                f"music-{master_id}: jacket {jacket_name!r} is not available"
            )
        if unresolved_bands or unresolved_vocalists:
            warnings.append(
                f"music-{master_id}: partial staging relations "
                f"bands={unresolved_bands} vocalists={unresolved_vocalists}"
            )

        expert_chart = track_charts[-1]
        bpm_min = min(chart["bpm"]["min"] for chart in track_charts)
        bpm_max = max(chart["bpm"]["max"] for chart in track_charts)
        score_rank_group = row.get("_liveScoreRankGroup")
        if not isinstance(score_rank_group, int) or isinstance(
            score_rank_group,
            bool,
        ):
            raise MusicCatalogError(
                f"music {master_id} has invalid score rank group "
                f"{score_rank_group!r}"
            )
        score_rank_entries = score_ranks_by_group.get(score_rank_group)
        if not score_rank_entries:
            raise MusicCatalogError(
                f"music {master_id} references missing score rank group "
                f"{score_rank_group}"
            )
        score_rank_lookup = {
            int(entry.get("_liveScoreRank", 0)): int(
                entry.get("_requiredScore", 0)
            )
            for entry in score_rank_entries
        }
        score_reward_group = row.get("_scoreRankRewardGroup")
        if not isinstance(score_reward_group, int) or isinstance(
            score_reward_group,
            bool,
        ):
            raise MusicCatalogError(
                f"music {master_id} has invalid score reward group "
                f"{score_reward_group!r}"
            )
        track_score_rewards = score_rewards_by_group.get(score_reward_group)
        if not track_score_rewards:
            raise MusicCatalogError(
                f"music {master_id} references missing score reward group "
                f"{score_reward_group}"
            )
        seen_score_reward_ranks: set[int] = set()
        projected_score_rewards = []
        for reward in sorted(
            track_score_rewards,
            key=lambda entry: int(entry.get("_liveScoreRank", -1)),
        ):
            rank = reward.get("_liveScoreRank")
            if (
                not isinstance(rank, int)
                or isinstance(rank, bool)
                or rank not in score_rank_lookup
            ):
                raise MusicCatalogError(
                    f"music {master_id} score reward group "
                    f"{score_reward_group} has unknown score rank {rank!r}"
                )
            if rank in seen_score_reward_ranks:
                raise MusicCatalogError(
                    f"music {master_id} score reward group "
                    f"{score_reward_group} duplicates score rank {rank}"
                )
            seen_score_reward_ranks.add(rank)
            projected_score_rewards.append(
                {
                    "liveScoreRank": rank,
                    "requiredScore": score_rank_lookup[rank],
                    "entry": reward_resource(
                        reward,
                        master_id,
                        f"score reward rank {rank}",
                    ),
                }
            )
        combo_reward_group = row.get("_comboRewardGroup")
        if not isinstance(combo_reward_group, int) or isinstance(
            combo_reward_group,
            bool,
        ):
            raise MusicCatalogError(
                f"music {master_id} has invalid combo reward group "
                f"{combo_reward_group!r}"
            )
        track_combo_rewards = combo_rewards_by_group.get(combo_reward_group)
        if not track_combo_rewards:
            raise MusicCatalogError(
                f"music {master_id} references missing combo reward group "
                f"{combo_reward_group}"
            )
        seen_combo_rewards: set[tuple[int, int]] = set()
        projected_combo_rewards = []
        for reward in sorted(
            track_combo_rewards,
            key=lambda entry: (
                int(entry.get("_difficulty", -1)),
                int(entry.get("_comboRateType", -1)),
            ),
        ):
            difficulty_code = reward.get("_difficulty")
            combo_rate_type = reward.get("_comboRateType")
            if (
                not isinstance(difficulty_code, int)
                or isinstance(difficulty_code, bool)
                or difficulty_code not in DIFFICULTY_BY_CODE
            ):
                raise MusicCatalogError(
                    f"music {master_id} combo reward group "
                    f"{combo_reward_group} has unknown difficulty "
                    f"{difficulty_code!r}"
                )
            if (
                not isinstance(combo_rate_type, int)
                or isinstance(combo_rate_type, bool)
                or combo_rate_type not in COMBO_RATE_TYPES
            ):
                raise MusicCatalogError(
                    f"music {master_id} combo reward group "
                    f"{combo_reward_group} has unknown combo rate "
                    f"{combo_rate_type!r}"
                )
            reward_key = (difficulty_code, combo_rate_type)
            if reward_key in seen_combo_rewards:
                raise MusicCatalogError(
                    f"music {master_id} combo reward group "
                    f"{combo_reward_group} duplicates {reward_key}"
                )
            seen_combo_rewards.add(reward_key)
            projected_combo_rewards.append(
                {
                    "difficulty": DIFFICULTY_BY_CODE[difficulty_code],
                    "comboRateType": combo_rate_type,
                    "entry": reward_resource(
                        reward,
                        master_id,
                        (
                            "combo reward "
                            f"{difficulty_code}:{combo_rate_type}"
                        ),
                    ),
                }
            )
        solo_rewards = {
            "scoreRanks": [
                {
                    "rank": int(entry.get("_liveScoreRank", 0)),
                    "requiredScore": int(entry.get("_requiredScore", 0)),
                }
                for entry in sorted(
                    score_rank_entries,
                    key=lambda item: int(item.get("_liveScoreRank", 0)),
                )
            ],
            "scoreRewards": projected_score_rewards,
            "comboRewards": projected_combo_rewards,
        }
        tracks.append(
            {
                "id": f"music-{master_id}",
                "masterId": master_id,
                "title": title,
                "phoneticTitle": _text(texts, row.get("_phoneticTextID")),
                "rubyTitle": _text(texts, row.get("_rubyTitleTextID")),
                "sortOrder": int(row.get("_sortOrder", 0)),
                "bandIds": [f"band-{value}" for value in band_ids],
                "bandLabels": band_labels,
                "vocalCharacterIds": [
                    f"character-{value}" for value in vocalist_ids
                ],
                "vocalistLabels": vocalist_labels,
                "musicType": int(row.get("_musicType", 0)),
                "musicTypeLabel": tag_labels.get(
                    row.get("_musicType"),
                    f"类型 {row.get('_musicType', 0)}",
                ),
                "categoryIds": category_ids,
                "categoryLabels": [
                    category_labels[value] for value in category_ids
                ],
                "tagIds": tag_ids,
                "tagLabels": [
                    tag_labels.get(value, f"标签 {value}") for value in tag_ids
                ],
                "lyricist": _text(texts, row.get("_lyricistTextID")),
                "composer": _text(texts, row.get("_composerTextID")),
                "arranger": _text(texts, row.get("_arrangerTextID")),
                "startAt": str(row.get("_startAt") or ""),
                "jacketAssetId": jacket_asset_id,
                "chartIds": track_chart_ids,
                "musicSoundId": row.get("_musicSoundID"),
                "jingleSoundId": row.get("_jingleSoundID"),
                "audioStatus": "missing",
                "audioPlayback": False,
                "audioDownload": False,
                "maxLevel": max(chart["level"] for chart in track_charts),
                "expertNoteCount": expert_chart["fullComboCount"],
                "bpm": {"min": bpm_min, "max": bpm_max},
                "hasCompleteCharts": True,
                "gekisouMissions": gekisou_missions(row, master_id),
                "soloRewards": solo_rewards,
                "sourceReleaseIds": [release_id],
                "catalogStatus": (
                    "missing_asset" if not jacket_asset_id else "identified"
                ),
                "relationStatus": (
                    "partial"
                    if unresolved_bands or unresolved_vocalists
                    else "identified"
                ),
            }
        )

    for logical_path in sorted(set(score_payloads) - used_score_paths):
        warnings.append(f"unlinked music score payload: {logical_path}")

    return MusicCatalogResult(
        tracks=tracks,
        charts=charts,
        chart_data=chart_data,
        warnings=warnings,
    )
