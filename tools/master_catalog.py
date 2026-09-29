"""Build verified site entities from decrypted Master tables and Unity paths."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from tools.resource_pipeline.localization import (
    DEFAULT_FALLBACK_ORDER,
    extract_localized_text,
    resolve_localized_text,
)


class MasterCatalogError(ValueError):
    """Raised when Master data or a verified resource relationship is invalid."""


@dataclass(frozen=True)
class MasterData:
    characters: dict[int, dict[str, Any]]
    bands: dict[int, dict[str, Any]]
    member_cards: dict[int, dict[str, Any]]
    support_cards: dict[int, dict[str, Any]]
    texts: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ResourceIdentity:
    kind: str
    asset_id: int


RESOURCE_PATTERNS = (
    (
        re.compile(
            r"^Assets/AddressableResources/Character/Image/"
            r"(?P<id>\d+)/[^/]+\.png$"
        ),
        "character",
    ),
    (
        re.compile(
            r"^Assets/AddressableResources/MemberCard/"
            r"(?P<id>\d+)/[^/]+\.png$"
        ),
        "member_card",
    ),
    (
        re.compile(
            r"^Assets/AddressableResources/SupportCard/"
            r"(?P<id>\d+)/[^/]+\.png$"
        ),
        "support_card",
    ),
)


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise MasterCatalogError(f"missing Master table: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise MasterCatalogError(f"invalid JSON in {path}: {exc}") from exc
    rows = value.get("_allData") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise MasterCatalogError(f"{name} must contain an _allData array")
    return rows


def _unique_index(
    rows: Iterable[dict[str, Any]],
    field: str,
    label: str,
    key_type: type[int] | type[str],
) -> dict[Any, dict[str, Any]]:
    index: dict[Any, dict[str, Any]] = {}
    for row in rows:
        raw_key = row.get(field)
        if not isinstance(raw_key, key_type):
            raise MasterCatalogError(
                f"{label} row has invalid {field}: {raw_key!r}"
            )
        if raw_key in index:
            raise MasterCatalogError(f"duplicate {label} {field}: {raw_key}")
        index[raw_key] = row
    return index


def load_master_data(root: Path) -> MasterData:
    return MasterData(
        characters=_unique_index(
            _load_table(root, "MasterCharacter"),
            "_id",
            "character",
            int,
        ),
        bands=_unique_index(
            _load_table(root, "MasterBand"),
            "_id",
            "band",
            int,
        ),
        member_cards=_unique_index(
            _load_table(root, "MasterMemberCard"),
            "_assetID",
            "member card asset",
            int,
        ),
        support_cards=_unique_index(
            _load_table(root, "MasterSupportCard"),
            "_assetID",
            "support card asset",
            int,
        ),
        texts=_unique_index(
            _load_table(root, "MasterText"),
            "_id",
            "text",
            str,
        ),
    )


def parse_resource_identity(container_path: str | None) -> ResourceIdentity | None:
    if not container_path:
        return None
    for pattern, kind in RESOURCE_PATTERNS:
        match = pattern.fullmatch(container_path)
        if match:
            return ResourceIdentity(kind=kind, asset_id=int(match.group("id")))
    return None


def _text_values(master: MasterData, *text_ids: Any) -> list[str]:
    values: list[str] = []
    for text_id in text_ids:
        if not isinstance(text_id, str) or not text_id:
            continue
        row = master.texts.get(text_id)
        if not row:
            continue
        localized = extract_localized_text(row)
        for locale in DEFAULT_FALLBACK_ORDER:
            value = localized.get(locale)
            if value and value not in values:
                values.append(value)
    return values


def resolve_text(
    master: MasterData,
    text_id: Any,
    fallback: str,
    locale: str = "zh-CN",
) -> str:
    row = master.texts.get(text_id) if isinstance(text_id, str) else None
    return resolve_localized_text(row, locale, fallback).text


def localized_text(master: MasterData, text_id: Any) -> dict[str, str]:
    row = master.texts.get(text_id) if isinstance(text_id, str) else None
    return extract_localized_text(row)


def build_character_profile(
    master: MasterData, row: dict[str, Any], locale: str = "zh-CN"
) -> dict[str, str]:
    """Resolve package profile fields; absent text stays absent, never a text ID."""
    fields = {
        "voiceActor": "_voiceActorTextId",
        "description": "_descriptionTextId",
        "catchphrase": "_catchCopyTextId",
        "bloodType": "_bloodTypeTextId",
        "height": "_heightTextId",
        "constellation": "_constellationTextId",
        "school": "_schoolTextId",
        "schoolClass": "_schoolClassTextId",
        "favoriteFood": "_favoriteFoodTextId",
        "hobby": "_hobbyTextId",
    }
    return {
        field: resolve_text(master, row.get(source), "", locale)
        .replace("\r\n", "\n").strip()
        for field, source in fields.items()
    }


def _combined_localized_text(
    left: dict[str, str],
    right: dict[str, str],
    separator: str,
) -> dict[str, str]:
    return {
        locale: separator.join(
            value
            for value in (left.get(locale), right.get(locale))
            if value
        )
        for locale in set(left) | set(right)
        if left.get(locale) or right.get(locale)
    }


def _entity_id(kind: str, master_id: int) -> str:
    return f"{kind}-{master_id}"


def _related_assets(
    group: list[dict[str, Any]],
    asset_ids: dict[str, str],
) -> list[str]:
    return sorted(
        {
            asset_ids[str(record["source_file"])]
            for record in group
            if str(record["source_file"]) in asset_ids
        }
    )


def _choose_asset(
    group: list[dict[str, Any]],
    asset_ids: dict[str, str],
    *names: str,
) -> str | None:
    for name in names:
        for record in group:
            if str(record.get("name", "")).lower() == name:
                return asset_ids.get(str(record["source_file"]))
    return None


def _source_bundle(group: list[dict[str, Any]]) -> str:
    bundles = sorted(
        {
            str(record.get("bundle", ""))
            for record in group
            if record.get("bundle")
        }
    )
    return bundles[0] if bundles else ""


def _source_container(group: list[dict[str, Any]]) -> str:
    paths = sorted(
        {
            str(record.get("container_path", ""))
            for record in group
            if record.get("container_path")
        }
    )
    return paths[0] if paths else ""


def _legacy_member_card_id(group: list[dict[str, Any]]) -> str | None:
    bundle = _source_bundle(group)
    if not bundle:
        return None
    digest = hashlib.sha1(bundle.encode("utf-8")).hexdigest()[:10]
    return f"card-{digest}"


def _validated_groups(
    master: MasterData,
    records: list[dict[str, Any]],
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    known = {
        "character": master.characters,
        "member_card": master.member_cards,
        "support_card": master.support_cards,
    }
    for record in records:
        identity = parse_resource_identity(
            str(record.get("container_path", "")) or None
        )
        if not identity:
            continue
        if identity.asset_id not in known[identity.kind]:
            raise MasterCatalogError(
                f"{record.get('container_path')} has no matching "
                f"{identity.kind} Master record"
            )
        groups[(identity.kind, identity.asset_id)].append(record)
    return dict(groups)


def build_master_entities(
    master: MasterData,
    records: list[dict[str, Any]],
    asset_ids: dict[str, str],
    release_id: str,
    locale: str = "zh-CN",
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    groups = _validated_groups(master, records)
    asset_labels: dict[str, str] = {}

    bands = []
    for band_id, row in sorted(master.bands.items()):
        bands.append(
            {
                "id": _entity_id("band", band_id),
                "masterId": band_id,
                "displayName": resolve_text(
                    master,
                    row.get("_nameTextID"),
                    f"Band {band_id}",
                    locale,
                ),
                "localizedText": localized_text(
                    master, row.get("_nameTextID")
                ),
                "description": resolve_text(
                    master,
                    row.get("_descriptionTextID"),
                    "",
                    locale,
                ),
                "mainColor": str(row.get("_mainColorCode", "")).strip(),
                "subColor": str(row.get("_subColorCode", "")).strip(),
                "characterIds": [],
                "sourceReleaseIds": [release_id],
                "catalogStatus": "identified",
            }
        )

    characters = []
    for character_id, row in sorted(master.characters.items()):
        group = groups.get(("character", character_id), [])
        related_asset_ids = _related_assets(group, asset_ids)
        profile_asset_id = _choose_asset(
            group,
            asset_ids,
            "character_thumbnail",
            "character_sprite",
        )
        name = resolve_text(
            master,
            row.get("_nameTextID"),
            f"Character {character_id}",
            locale,
        )
        aliases = _text_values(
            master,
            row.get("_nameTextID"),
            row.get("_shortNameTextID"),
            row.get("_enDisplayNameTextId"),
        )
        aliases = [value for value in aliases if value != name]
        for record in group:
            suffix = {
                "character_thumbnail": "角色缩略图",
                "character_sprite": "角色立绘",
            }.get(str(record.get("name", "")).lower(), "角色素材")
            asset_id = asset_ids.get(str(record["source_file"]))
            if asset_id:
                asset_labels[asset_id] = f"{name} · {suffix}"
        characters.append(
            {
                "id": _entity_id("character", character_id),
                "masterId": character_id,
                "displayName": name,
                "localizedText": localized_text(
                    master, row.get("_nameTextID")
                ),
                "shortName": resolve_text(
                    master,
                    row.get("_shortNameTextID"),
                    name,
                    locale,
                ),
                "aliases": aliases,
                "bandId": _entity_id("band", int(row["_bandID"])),
                "role": str(row.get("_bandPart", "")).strip(),
                "profile": build_character_profile(master, row, locale),
                "birthday": {
                    "month": int(row.get("_birthdayMonth", 0)),
                    "day": int(row.get("_birthdayDay", 0)),
                },
                "mainColor": str(row.get("_mainColorCode", "")).strip(),
                "subColor": str(row.get("_subColorCode", "")).strip(),
                "profileAssetId": profile_asset_id,
                "portraitAssetIds": related_asset_ids,
                "memberCardIds": [],
                "featuredSupportCardIds": [],
                "sourceReleaseIds": [release_id],
                "catalogStatus": (
                    "identified" if profile_asset_id else "missing_asset"
                ),
                "sourceBundle": _source_bundle(group),
            }
        )

    character_ids = {
        character["masterId"]: character["id"] for character in characters
    }
    band_ids = {band["masterId"]: band["id"] for band in bands}
    for character in characters:
        if character["bandId"] not in band_ids.values():
            raise MasterCatalogError(
                f"{character['id']} references missing band "
                f"{character['bandId']}"
            )
    characters_by_id = {character["id"]: character for character in characters}
    bands_by_id = {band["id"]: band for band in bands}
    for character in characters:
        bands_by_id[character["bandId"]]["characterIds"].append(
            character["id"]
        )

    member_cards = []
    for asset_id, row in sorted(master.member_cards.items()):
        master_id = int(row["_id"])
        group = groups.get(("member_card", asset_id), [])
        primary_asset_id = _choose_asset(group, asset_ids, "member_full")
        character_master_id = int(row["_characterID"])
        character_id = character_ids.get(character_master_id)
        if not character_id:
            raise MasterCatalogError(
                f"member card {master_id} references missing character "
                f"{character_master_id}"
            )
        name = resolve_text(
            master,
            row.get("_nameTextID"),
            characters_by_id[character_id]["displayName"],
            locale,
        )
        subtitle = resolve_text(
            master,
            row.get("_subtitleTextID"),
            f"Member Card {master_id}",
            locale,
        )
        display_name = f"{name}｜{subtitle}"
        display_localized = _combined_localized_text(
            localized_text(master, row.get("_nameTextID")),
            localized_text(master, row.get("_subtitleTextID")),
            "｜",
        )
        for record in group:
            related_asset_id = asset_ids.get(str(record["source_file"]))
            if related_asset_id:
                asset_labels[related_asset_id] = f"{display_name} · 成员卡"
        entity_id = _entity_id("member-card", master_id)
        member_cards.append(
            {
                "id": entity_id,
                "legacyId": _legacy_member_card_id(group),
                "masterId": master_id,
                "assetId": asset_id,
                "displayName": display_name,
                "localizedText": display_localized,
                "name": name,
                "subtitle": subtitle,
                "characterId": character_id,
                "rarity": int(row.get("_rarity", 0)),
                "attributeCode": int(row.get("_cardType", 0)),
                "performancePowerMax": int(
                    row.get("_performancePowerMax", 0)
                ),
                "technicPowerMax": int(row.get("_technicPowerMax", 0)),
                "visualPowerMax": int(row.get("_visualPowerMax", 0)),
                "leaderSkillId": int(row.get("_leaderSkillID", 0)),
                "liveSkillId": int(row.get("_liveSkillID", 0)),
                "startAt": str(row.get("_startAt", "")),
                "primaryAssetId": primary_asset_id,
                "variantAssetIds": _related_assets(group, asset_ids),
                "thumbnailAssetId": primary_asset_id,
                "sourceReleaseIds": [release_id],
                "catalogStatus": (
                    "identified" if primary_asset_id else "missing_asset"
                ),
                "sourceBundle": _source_bundle(group),
                "sourceContainerPath": _source_container(group),
            }
        )
        characters_by_id[character_id]["memberCardIds"].append(entity_id)

    support_cards = []
    for asset_id, row in sorted(master.support_cards.items()):
        master_id = int(row["_id"])
        group = groups.get(("support_card", asset_id), [])
        primary_asset_id = _choose_asset(group, asset_ids, "snap_full")
        featured_character_ids = []
        for raw_character_id in row.get("_characterIDs", []):
            character_id = character_ids.get(int(raw_character_id))
            if not character_id:
                raise MasterCatalogError(
                    f"support card {master_id} references missing character "
                    f"{raw_character_id}"
                )
            featured_character_ids.append(character_id)
        name = resolve_text(
            master,
            row.get("_nameTextID"),
            f"Snap {master_id}",
            locale,
        )
        description = resolve_text(
            master,
            row.get("_descriptionTextID"),
            "",
            locale,
        )
        display_name = f"{name}｜{description}" if description else name
        display_localized = _combined_localized_text(
            localized_text(master, row.get("_nameTextID")),
            localized_text(master, row.get("_descriptionTextID")),
            "｜",
        )
        for record in group:
            related_asset_id = asset_ids.get(str(record["source_file"]))
            if related_asset_id:
                asset_labels[related_asset_id] = f"{display_name} · 留影"
        support_skill_ids = [
            int(value)
            for key in ("_supportSkillId01", "_supportSkillId02")
            if (value := row.get(key)) and isinstance(value, int)
        ]
        entity_id = _entity_id("support-card", master_id)
        support_cards.append(
            {
                "id": entity_id,
                "masterId": master_id,
                "assetId": asset_id,
                "displayName": display_name,
                "localizedText": display_localized,
                "name": name,
                "description": description,
                "diary": resolve_text(
                    master, row.get("_diaryTextID"), "", locale,
                ).replace("\r\n", "\n").replace("\r", "\n"),
                "featuredCharacterIds": featured_character_ids,
                "rarity": int(row.get("_rarity", 0)),
                "attributeCode": int(row.get("_cardType", 0)),
                "performancePowerMax": int(
                    row.get("_performancePowerMax", 0)
                ),
                "technicPowerMax": int(row.get("_technicPowerMax", 0)),
                "visualPowerMax": int(row.get("_visualPowerMax", 0)),
                "supportSkillIds": support_skill_ids,
                "startAt": str(row.get("_startAt", "")),
                "primaryAssetId": primary_asset_id,
                "variantAssetIds": _related_assets(group, asset_ids),
                "thumbnailAssetId": primary_asset_id,
                "sourceReleaseIds": [release_id],
                "catalogStatus": (
                    "identified" if primary_asset_id else "missing_asset"
                ),
                "sourceBundle": _source_bundle(group),
                "sourceContainerPath": _source_container(group),
            }
        )
        for character_id in featured_character_ids:
            characters_by_id[character_id][
                "featuredSupportCardIds"
            ].append(entity_id)

    return (
        {
            "bands": bands,
            "characters": characters,
            "memberCards": member_cards,
            "supportCards": support_cards,
        },
        asset_labels,
    )
