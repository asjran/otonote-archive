"""Normalize story Master tables into a capability-tiered public archive.

The story module handles four user-visible story kinds:

* ``main`` — ordered chapter + episode arcs from MasterStoryEpisode.
* ``friendship`` — character friendship arcs from MasterStoryFriendshipEpisode.
* ``home_spot`` — home screen tap dialogues from MasterStoryHomeSpotTapTalkEpisode.
* ``live_result`` — post-live result dialogues from MasterStoryLiveResultEpisode.

The module never opens ``phone_dump`` from the page layer — pages consume only
the deterministic JSON artifacts produced here.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.master_catalog import MasterData
from tools.resource_pipeline.localization import resolve_localized_text


STORY_KINDS = ("main", "friendship", "home_spot", "live_result")


class StoryCatalogError(ValueError):
    """Raised when story inputs violate publishing invariants."""


@dataclass(frozen=True)
class StoryCatalogBuild:
    chapters: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    adv_index: dict[int, dict[str, Any]]
    friendship_groups: dict[int, list[dict[str, Any]]]
    home_spots: dict[int, dict[str, Any]]
    live_result_characters: dict[int, list[int]]
    reward_groups: dict[int, list[dict[str, Any]]]
    warnings: list[str] = field(default_factory=list)


REQUIRED_TABLES = (
    "MasterStoryChapter",
    "MasterStoryEpisode",
    "MasterStoryFriendshipEpisode",
    "MasterStoryHomeSpotTapTalkEpisode",
    "MasterStoryLiveResultEpisode",
    "MasterAdv",
    "MasterAdvChat",
    "MasterAdvPlayTime",
    "MasterHomeSpot",
    "MasterStoryReward",
    "MasterCharacterFriendship",
)


PLACEHOLDER_VALUES = {"", "TBD", "TODO", "0"}


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise StoryCatalogError(f"missing Master table: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise StoryCatalogError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise StoryCatalogError(f"{name} must contain an _allData array")
    return rows


def _index(rows: Iterable[dict[str, Any]], field_name: str, label: str) -> dict[int, dict[str, Any]]:
    index: dict[int, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field_name)
        if not isinstance(key, int):
            raise StoryCatalogError(
                f"{label} row has invalid {field_name}: {key!r}"
            )
        if key in index:
            raise StoryCatalogError(
                f"duplicate {label} {field_name}: {key}"
            )
        index[key] = row
    return index


def _text(
    master: MasterData,
    text_id: Any,
    fallback: str = "",
) -> str:
    if not isinstance(text_id, str) or not text_id:
        return fallback
    row = master.texts.get(text_id)
    if not row:
        return fallback
    return resolve_localized_text(row, "zh-CN", fallback).text


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().upper() in PLACEHOLDER_VALUES:
        return True
    return False


def _stable_chapter_id(master_id: int) -> str:
    return f"story-chapter-{master_id}"


def _stable_entry_id(kind: str, master_id: int) -> str:
    return f"story-entry-{kind}-{master_id}"


def _character_id(master_id: int) -> str:
    return f"character-{master_id}"


def _band_id(master_id: int) -> str:
    return f"band-{master_id}"


def _music_id(master_id: int) -> str:
    return f"music-{master_id}"


def _adv_id(master_id: int) -> str:
    return f"adv-{master_id}"


def _home_spot_id(master_id: int) -> str:
    return f"home-spot-{master_id}"


def _reward_id(group: int, slot: int) -> str:
    return f"story-reward-{group}-{slot}"


def _reward_group(group: int) -> str:
    return f"story-reward-group-{group}"


def _character_friendship_id(master_id: int) -> str:
    return f"character-friendship-{master_id}"


def _resolve_adv(
    adv_index: Mapping[int, dict[str, Any]],
    adv_id: Any,
    *,
    warnings: list[str],
    entry_id: str,
) -> dict[str, Any] | None:
    if not isinstance(adv_id, int) or adv_id <= 0:
        return None
    row = adv_index.get(adv_id)
    if not row:
        warnings.append(
            f"{entry_id} references missing adv id {adv_id}"
        )
        return None
    sheet_name = _clean_name(row.get("_sheetName"))
    episode_asset = _clean_name(row.get("_advEpisodeAsset"))
    playback_mode = int(row.get("_playbackMode") or 0)
    title_text_id = row.get("_titleTextId")
    return {
        "advId": _adv_id(adv_id),
        "masterId": adv_id,
        "sheetName": sheet_name,
        "episodeAsset": episode_asset,
        "titleTextId": title_text_id if isinstance(title_text_id, str) else "",
        "playbackMode": playback_mode,
    }


def _reward_payloads(
    reward_rows: list[dict[str, Any]],
    master: MasterData,
    group: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    payloads: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(sorted(reward_rows, key=lambda item: item["_id"])):
        resource_type = int(row.get("_resourceType") or 0)
        resource_id = int(row.get("_resourceId") or 0)
        count = int(row.get("_resourceCount") or 0)
        payloads.append(
            {
                "id": _reward_id(group, index),
                "group": group,
                "slot": index,
                "resourceType": resource_type,
                "resourceId": resource_id,
                "count": count,
                "catalogStatus": "identified",
            }
        )
    return payloads, warnings


def _index_rewards(root: Path) -> dict[int, list[dict[str, Any]]]:
    rows = _load_table(root, "MasterStoryReward")
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group = row.get("_group")
        if not isinstance(group, int):
            raise StoryCatalogError(
                f"reward row has invalid _group: {row.get('_group')!r}"
            )
        grouped[group].append(row)
    return dict(grouped)


def _build_adv_index(root: Path) -> dict[int, dict[str, Any]]:
    rows = _load_table(root, "MasterAdv")
    return _index(rows, "_id", "adv")


def _build_friendship_groups(
    root: Path,
) -> dict[int, list[dict[str, Any]]]:
    rows = _load_table(root, "MasterCharacterFriendship")
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        character_id = row.get("_characterID")
        if not isinstance(character_id, int):
            continue
        grouped[character_id].append(row)
    return dict(grouped)


def _build_home_spots(root: Path) -> dict[int, dict[str, Any]]:
    rows = _load_table(root, "MasterHomeSpot")
    return _index(rows, "_id", "home spot")


def _live_character_lookup(
    root: Path,
) -> dict[int, list[int]]:
    rows = _load_table(root, "MasterStoryLiveResultEpisode")
    mapping: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        for character_id in row.get("_characterIds") or []:
            if isinstance(character_id, int):
                mapping[row["_id"]].append(character_id)
    return dict(mapping)


def _normalize_chapter(
    row: dict[str, Any],
    master: MasterData,
    adv_index: Mapping[int, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    master_id = int(row["_id"])
    name = _text(master, row.get("_nameTextId"), f"Chapter {master_id}")
    description = _text(master, row.get("_descriptionTextId"), "")
    band_master_id = int(row.get("_bandId") or 0)
    music_master_id = int(row.get("_musicId") or 0)
    main_character_ids = [
        int(value)
        for value in row.get("_mainCharacterIds") or []
        if isinstance(value, int)
    ]
    event_id = int(row.get("_eventId") or 0)
    start_at = str(row.get("_startAt") or "")
    end_at = str(row.get("_endAt") or "")
    banner = _clean_name(row.get("_banner"))
    image = _clean_name(row.get("_image"))
    icon = _clean_name(row.get("_icon"))
    is_special = bool(row.get("_isSpecialStory"))

    for character_master_id in main_character_ids:
        if character_master_id not in master.characters:
            warnings.append(
                f"{_stable_chapter_id(master_id)} references missing "
                f"character id {character_master_id}"
            )
    if band_master_id and band_master_id not in master.bands:
        warnings.append(
            f"{_stable_chapter_id(master_id)} references missing band "
            f"{band_master_id}"
        )

    return {
        "id": _stable_chapter_id(master_id),
        "masterId": master_id,
        "name": name,
        "description": description,
        "bandId": _band_id(band_master_id) if band_master_id else None,
        "bandMasterId": band_master_id or None,
        "mainCharacterIds": [
            _character_id(value) for value in main_character_ids
        ],
        "mainCharacterMasterIds": main_character_ids,
        "musicId": _music_id(music_master_id) if music_master_id else None,
        "musicMasterId": music_master_id or None,
        "eventId": event_id or None,
        "isSpecialStory": is_special,
        "startAt": start_at,
        "endAt": end_at,
        "bannerAssetName": banner,
        "imageAssetName": image,
        "iconAssetName": icon,
        "episodeIds": [],
        "source": {
            "table": "MasterStoryChapter",
            "masterId": master_id,
        },
    }


def _normalize_main_episode(
    row: dict[str, Any],
    chapter_id: str,
    master: MasterData,
    adv_index: Mapping[int, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    master_id = int(row["_id"])
    chapter_master_id = int(row.get("_chapterId") or 0)
    episode_number = int(row.get("_episodeNumber") or 0)
    description_text_id = row.get("_descriptionTextId")
    description = _text(master, description_text_id, "")
    adv_master_id = int(row.get("_advId") or 0)
    character_master_id = int(row.get("_characterId") or 0)
    is_another = bool(row.get("_isAnotherEpisode"))
    is_extra = bool(row.get("_isExtraEpisode"))
    unlock_episode_number = int(row.get("_unlockEpisodeNumber") or 0)
    event_point = int(row.get("_eventPoint") or 0)
    character_rank = int(row.get("_characterRank") or 0)
    friendship_master_id = int(row.get("_storyFriendshipEpisodeId") or 0)
    story_reward_group = int(row.get("_storyRewardGroupId") or 0)
    event_reward_group = int(row.get("_eventStoryRewardGroupId") or 0)
    is_event_second_half = bool(row.get("_isEventSecondHalfEpisode"))
    banner = _clean_name(row.get("_banner"))
    image = _clean_name(row.get("_image"))
    thumbnail = _clean_name(row.get("_thumbnail"))

    if chapter_master_id and chapter_id != _stable_chapter_id(chapter_master_id):
        raise StoryCatalogError(
            f"episode {master_id} declares chapter {chapter_master_id} "
            f"but normalization produced {chapter_id}"
        )

    entry_id = _stable_entry_id("main", master_id)
    adv = _resolve_adv(
        adv_index,
        adv_master_id,
        warnings=warnings,
        entry_id=entry_id,
    )

    return {
        "id": entry_id,
        "kind": "main",
        "masterId": master_id,
        "chapterId": chapter_id,
        "chapterMasterId": chapter_master_id,
        "episodeNumber": episode_number,
        "description": description,
        "adv": adv,
        "primaryCharacterIds": (
            [_character_id(character_master_id)]
            if character_master_id
            else []
        ),
        "isAnotherEpisode": is_another,
        "isExtraEpisode": is_extra,
        "unlockEpisodeNumber": unlock_episode_number,
        "unlockCharacterFriendshipLevel": 0,
        "eventPoint": event_point,
        "characterRank": character_rank,
        "friendshipEpisodeId": (
            _stable_entry_id("friendship", friendship_master_id)
            if friendship_master_id
            else None
        ),
        "friendshipMasterId": friendship_master_id or None,
        "rewardGroupId": story_reward_group or None,
        "eventRewardGroupId": event_reward_group or None,
        "homeSpotId": None,
        "homeSpotMasterId": None,
        "characterCombination": [],
        "locationId": None,
        "locationName": "",
        "bannerAssetName": banner,
        "imageAssetName": image,
        "thumbnailAssetName": (
            "" if _is_placeholder(thumbnail) else thumbnail
        ),
        "thumbnailIsPlaceholder": _is_placeholder(thumbnail),
        "playbackMode": adv["playbackMode"] if adv else 0,
        "sheetName": adv["sheetName"] if adv else "",
        "advEpisodeAsset": adv["episodeAsset"] if adv else "",
        "title": adv["titleTextId"] if adv else "",
        "source": {
            "table": "MasterStoryEpisode",
            "masterId": master_id,
        },
    }


def _normalize_friendship_entry(
    row: dict[str, Any],
    master: MasterData,
    adv_index: Mapping[int, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    master_id = int(row["_id"])
    friendship_master_id = int(row.get("_characterFriendshipId") or 0)
    episode_number = int(row.get("_episodeNumber") or 0)
    adv_master_id = int(row.get("_advId") or 0)
    unlock_level = int(row.get("_unlockCharacterFriendshipLevel") or 0)
    reward_group = int(row.get("_storyRewardGroupId") or 0)
    banner = _clean_name(row.get("_banner"))
    thumbnail = _clean_name(row.get("_thumbnail"))
    entry_id = _stable_entry_id("friendship", master_id)

    adv = _resolve_adv(
        adv_index,
        adv_master_id,
        warnings=warnings,
        entry_id=entry_id,
    )

    return {
        "id": entry_id,
        "kind": "friendship",
        "masterId": master_id,
        "chapterId": None,
        "chapterMasterId": None,
        "episodeNumber": episode_number,
        "description": "",
        "adv": adv,
        "primaryCharacterIds": (
            [_character_id(friendship_master_id)]
            if friendship_master_id
            else []
        ),
        "isAnotherEpisode": False,
        "isExtraEpisode": False,
        "unlockEpisodeNumber": 0,
        "unlockCharacterFriendshipLevel": unlock_level,
        "eventPoint": 0,
        "characterRank": 0,
        "friendshipEpisodeId": None,
        "friendshipMasterId": None,
        "friendshipGroupMasterId": friendship_master_id,
        "friendshipGroupId": (
            _character_friendship_id(friendship_master_id)
            if friendship_master_id
            else None
        ),
        "rewardGroupId": reward_group or None,
        "eventRewardGroupId": None,
        "homeSpotId": None,
        "homeSpotMasterId": None,
        "characterCombination": [],
        "locationId": None,
        "locationName": "",
        "bannerAssetName": banner,
        "imageAssetName": "",
        "thumbnailAssetName": (
            "" if _is_placeholder(thumbnail) else thumbnail
        ),
        "thumbnailIsPlaceholder": _is_placeholder(thumbnail),
        "playbackMode": adv["playbackMode"] if adv else 0,
        "sheetName": adv["sheetName"] if adv else "",
        "advEpisodeAsset": adv["episodeAsset"] if adv else "",
        "title": adv["titleTextId"] if adv else "",
        "source": {
            "table": "MasterStoryFriendshipEpisode",
            "masterId": master_id,
        },
    }


def _normalize_home_spot_entry(
    row: dict[str, Any],
    home_spots: Mapping[int, dict[str, Any]],
    master: MasterData,
    adv_index: Mapping[int, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    master_id = int(row["_id"])
    spot_master_id = int(row.get("_spotId") or 0)
    character_master_id = int(row.get("_characterId") or 0)
    adv_master_id = int(row.get("_advId") or 0)
    entry_id = _stable_entry_id("home_spot", master_id)

    adv = _resolve_adv(
        adv_index,
        adv_master_id,
        warnings=warnings,
        entry_id=entry_id,
    )

    spot_row = home_spots.get(spot_master_id) if spot_master_id else None
    location_id = _home_spot_id(spot_master_id) if spot_master_id else None
    location_name = (
        _text(master, spot_row.get("_advNameTextId"), "") if spot_row else ""
    )
    return {
        "id": entry_id,
        "kind": "home_spot",
        "masterId": master_id,
        "chapterId": None,
        "chapterMasterId": None,
        "episodeNumber": 0,
        "description": "",
        "adv": adv,
        "primaryCharacterIds": (
            [_character_id(character_master_id)]
            if character_master_id
            else []
        ),
        "isAnotherEpisode": False,
        "isExtraEpisode": False,
        "unlockEpisodeNumber": 0,
        "unlockCharacterFriendshipLevel": 0,
        "eventPoint": 0,
        "characterRank": 0,
        "friendshipEpisodeId": None,
        "friendshipMasterId": None,
        "rewardGroupId": None,
        "eventRewardGroupId": None,
        "homeSpotId": location_id,
        "homeSpotMasterId": spot_master_id or None,
        "characterCombination": [],
        "locationId": location_id,
        "locationName": location_name,
        "bannerAssetName": "",
        "imageAssetName": "",
        "thumbnailAssetName": "",
        "thumbnailIsPlaceholder": True,
        "playbackMode": adv["playbackMode"] if adv else 0,
        "sheetName": adv["sheetName"] if adv else "",
        "advEpisodeAsset": adv["episodeAsset"] if adv else "",
        "title": adv["titleTextId"] if adv else "",
        "source": {
            "table": "MasterStoryHomeSpotTapTalkEpisode",
            "masterId": master_id,
        },
    }


def _normalize_live_result_entry(
    row: dict[str, Any],
    master: MasterData,
    adv_index: Mapping[int, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    master_id = int(row["_id"])
    character_ids = [
        int(value)
        for value in row.get("_characterIds") or []
        if isinstance(value, int)
    ]
    unlock_level = int(row.get("_unlockCharacterFriendshipLevel") or 0)
    adv_master_id = int(row.get("_advId") or 0)
    entry_id = _stable_entry_id("live_result", master_id)

    adv = _resolve_adv(
        adv_index,
        adv_master_id,
        warnings=warnings,
        entry_id=entry_id,
    )

    return {
        "id": entry_id,
        "kind": "live_result",
        "masterId": master_id,
        "chapterId": None,
        "chapterMasterId": None,
        "episodeNumber": 0,
        "description": "",
        "adv": adv,
        "primaryCharacterIds": [],
        "isAnotherEpisode": False,
        "isExtraEpisode": False,
        "unlockEpisodeNumber": 0,
        "unlockCharacterFriendshipLevel": unlock_level,
        "eventPoint": 0,
        "characterRank": 0,
        "friendshipEpisodeId": None,
        "friendshipMasterId": None,
        "rewardGroupId": None,
        "eventRewardGroupId": None,
        "homeSpotId": None,
        "homeSpotMasterId": None,
        "characterCombination": [
            _character_id(value) for value in character_ids
        ],
        "characterCombinationMasterIds": character_ids,
        "locationId": None,
        "locationName": "",
        "bannerAssetName": "",
        "imageAssetName": "",
        "thumbnailAssetName": "",
        "thumbnailIsPlaceholder": True,
        "playbackMode": adv["playbackMode"] if adv else 0,
        "sheetName": adv["sheetName"] if adv else "",
        "advEpisodeAsset": adv["episodeAsset"] if adv else "",
        "title": adv["titleTextId"] if adv else "",
        "source": {
            "table": "MasterStoryLiveResultEpisode",
            "masterId": master_id,
        },
    }


def build_story_catalog(
    master_root: Path,
    master: MasterData,
) -> StoryCatalogBuild:
    """Build the chapter, entry, and supporting index from Master tables."""

    warnings: list[str] = []
    for table in REQUIRED_TABLES:
        _load_table(master_root, table)

    chapter_rows = _load_table(master_root, "MasterStoryChapter")
    episode_rows = _load_table(master_root, "MasterStoryEpisode")
    friendship_rows = _load_table(master_root, "MasterStoryFriendshipEpisode")
    home_spot_rows = _load_table(
        master_root, "MasterStoryHomeSpotTapTalkEpisode"
    )
    live_result_rows = _load_table(master_root, "MasterStoryLiveResultEpisode")

    adv_index = _build_adv_index(master_root)
    home_spots = _build_home_spots(master_root)
    rewards = _index_rewards(master_root)
    friendship_groups = _build_friendship_groups(master_root)
    live_characters = _live_character_lookup(master_root)

    chapters = [
        _normalize_chapter(
            row,
            master,
            adv_index,
            warnings,
        )
        for row in sorted(chapter_rows, key=lambda value: value["_id"])
    ]
    chapters_by_master_id = {row["masterId"]: row for row in chapters}

    entries: list[dict[str, Any]] = []
    main_episode_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(episode_rows, key=lambda value: value["_id"]):
        chapter_master_id = int(row.get("_chapterId") or 0)
        if chapter_master_id not in chapters_by_master_id:
            raise StoryCatalogError(
                f"main episode {row['_id']} references missing chapter "
                f"{chapter_master_id}"
            )
        chapter = chapters_by_master_id[chapter_master_id]
        entry = _normalize_main_episode(
            row,
            chapter["id"],
            master,
            adv_index,
            warnings,
        )
        entries.append(entry)
        main_episode_groups[chapter_master_id].append(entry)
        chapter["episodeIds"].append(entry["id"])

    for chapter in chapters:
        chapter["episodeIds"] = list(chapter["episodeIds"])

    for row in sorted(friendship_rows, key=lambda value: value["_id"]):
        entries.append(
            _normalize_friendship_entry(
                row,
                master,
                adv_index,
                warnings,
            )
        )

    for row in sorted(home_spot_rows, key=lambda value: value["_id"]):
        entries.append(
            _normalize_home_spot_entry(
                row,
                home_spots,
                master,
                adv_index,
                warnings,
            )
        )

    for row in sorted(live_result_rows, key=lambda value: value["_id"]):
        entries.append(
            _normalize_live_result_entry(
                row,
                master,
                adv_index,
                warnings,
            )
        )

    seen_entry_ids: set[str] = set()
    for entry in entries:
        if entry["id"] in seen_entry_ids:
            raise StoryCatalogError(
                f"duplicate story entry id: {entry['id']}"
            )
        seen_entry_ids.add(entry["id"])

    return StoryCatalogBuild(
        chapters=chapters,
        entries=entries,
        adv_index=adv_index,
        friendship_groups=friendship_groups,
        home_spots=home_spots,
        live_result_characters=live_characters,
        reward_groups=rewards,
        warnings=warnings,
    )
