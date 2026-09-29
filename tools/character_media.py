"""Build the public character-media archive from verified local evidence.

The page layer consumes the generated database and projections only.  Raw
Master files, extraction manifests, and CRI reports remain build inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.master_catalog import MasterData


class CharacterMediaError(ValueError):
    """Raised when character-media inputs violate publishing invariants."""


@dataclass(frozen=True)
class CharacterMediaBuild:
    database: dict[str, Any]
    projections: dict[str, Any]
    search_index: dict[str, Any]
    quality_report: dict[str, Any]
    capabilities: list[dict[str, Any]]
    audio_publications: list[dict[str, Any]]
    texture_publications: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


REQUIRED_TABLES = (
    "MasterCharacterCostume",
    "MasterCharacterVoice",
    "MasterTalk",
    "MasterCharacterFriendship",
    "MasterCharacterFriendshipRank",
    "MasterStoryFriendshipEpisode",
    "MasterLiveDialogueCommon",
    "MasterLiveDialogueFixedPair",
    "MasterLiveStartCharacterVoice",
    "MasterLiveGekisouVoice",
    "MasterLoadingComics",
    "MasterStamp",
    "MasterSound",
    "MasterSoundCueSheet",
)


VOICE_TYPE_LABELS = {
    0: "等级提升",
    1: "特训",
    2: "技能提升",
    3: "觉醒",
    4: "Live 通关",
    5: "Full Combo",
    6: "All Perfect",
    7: "分数评级",
    8: "对战第一",
    9: "对战优势",
    10: "对战劣势",
}


def _load_table(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    if not path.is_file():
        raise CharacterMediaError(f"missing Master table: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except json.JSONDecodeError as exc:
        raise CharacterMediaError(f"invalid JSON in {path}: {exc}") from exc
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) for row in rows
    ):
        raise CharacterMediaError(f"{name} must contain an _allData array")
    return rows


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _unique_index(
    rows: Iterable[dict[str, Any]],
    field: str,
    label: str,
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, int):
            raise CharacterMediaError(
                f"{label} row has invalid {field}: {key!r}"
            )
        if key in result:
            raise CharacterMediaError(f"duplicate {label} {field}: {key}")
        result[key] = row
    return result


def _resolve_text(master: MasterData, text_id: Any, fallback: str = "") -> str:
    if not isinstance(text_id, str) or not text_id:
        return fallback
    row = master.texts.get(text_id)
    if not row:
        return fallback
    for field_name in (
        "_japanese",
        "_simplifiedChinese",
        "_english",
        "_traditionalChinese",
    ):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _character_id(master_id: int) -> str:
    return f"character-{master_id}"


def _costume_id(master_id: int) -> str:
    return f"character-costume-{master_id}"


def _voice_id(master_id: int) -> str:
    return f"character-voice-{master_id}"


def _talk_id(master_id: int) -> str:
    return f"character-talk-{master_id}"


def _friendship_id(master_id: int) -> str:
    return f"character-friendship-{master_id}"


def _live_dialogue_id(master_id: int) -> str:
    return f"character-live-dialogue-{master_id}"


def _compact_hash(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


TEXTURE_OBJECT_PRIORITY = {"Sprite": 0, "Texture2D": 1}


def _select_texture_records(
    records: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Select one renderable texture object per exact container path."""

    selected: dict[str, dict[str, Any]] = {}
    for record in records:
        object_type = record.get("type")
        container = str(record.get("container_path") or "")
        if object_type not in TEXTURE_OBJECT_PRIORITY or not container:
            continue
        current = selected.get(container)
        if current is None or TEXTURE_OBJECT_PRIORITY[object_type] < (
            TEXTURE_OBJECT_PRIORITY[current.get("type")]
        ):
            selected[container] = record
    return selected


def _texture_candidate(
    record: Mapping[str, Any],
    *,
    manifest_root: Path,
    release_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Project texture evidence without inferring what the texture depicts."""

    container = str(record.get("container_path") or "")
    exported_file = str(record.get("exported_file") or "")
    source_path = manifest_root / exported_file
    available = bool(exported_file) and source_path.is_file()
    content_hash = _file_sha256(source_path) if available else None
    publication_id = (
        f"character-texture-{content_hash[:16]}" if content_hash else None
    )
    preview_url = (
        f"/media/character-textures/{publication_id}.png"
        if publication_id
        else None
    )
    candidate = {
        "id": f"character-texture-candidate-{_compact_hash(container)}",
        "name": str(record.get("name") or Path(container).stem),
        "state": "available" if available else "unsupported",
        "previewUrl": preview_url,
        "containerPath": container,
        "sourceBundle": str(record.get("bundle") or ""),
        "sourcePathId": str(record.get("path_id") or ""),
        "exportedFile": exported_file or None,
        "sha256": content_hash,
        "sourceReleaseId": release_id,
    }
    publication = (
        {
            "id": publication_id,
            "source": str(source_path),
            "publicUrl": preview_url,
            "sha256": content_hash,
        }
        if available and publication_id and preview_url
        else None
    )
    return candidate, publication


def _media_id(kind: str, master_id: int) -> str:
    return f"character-media-{kind}-{master_id}"


def _audio_id(sheet_name: str, cue_name: str) -> str:
    return f"audio-{_compact_hash(f'{sheet_name}:{cue_name}')}"


def _capability_id(owner_id: str, role: str) -> str:
    return f"media-{_compact_hash(f'{owner_id}:{role}')}"


def _manifest_records(
    manifest_path: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    payload = _load_json(manifest_path, {})
    rows = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CharacterMediaError(
            f"manifest must contain an assets array: {manifest_path}"
        )
    by_container: dict[str, dict[str, Any]] = {}
    clean_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_rows.append(row)
        container = str(row.get("container_path") or "")
        if container and container not in by_container:
            by_container[container] = row
    return by_container, clean_rows


def _catalog_asset_index(
    assets: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        container = str(asset.get("containerPath") or "")
        if container and container not in result:
            result[container] = dict(asset)
    return result


def _cri_sheet_name(source: Any) -> str:
    name = Path(str(source or "")).name
    return re.sub(r"_[0-9a-f]{32}$", "", name, flags=re.IGNORECASE)


def _resolve_report_output(report_path: Path, raw_output: Any) -> Path:
    output = Path(str(raw_output or ""))
    if output.is_absolute():
        return output
    candidates = [Path.cwd() / output]
    resolved_report = report_path.resolve()
    candidates.extend(parent / output for parent in resolved_report.parents)
    return next(
        (candidate for candidate in candidates if candidate.is_file()),
        output,
    )


def _audio_index(
    report_path: Path,
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    list[str],
]:
    report = _load_json(report_path, {})
    files = report.get("files") if isinstance(report, dict) else None
    if files is None:
        return {}, [f"CRI report not found or empty: {report_path}"]
    if not isinstance(files, list):
        raise CharacterMediaError(
            f"CRI report files must be an array: {report_path}"
        )

    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    warnings: list[str] = []
    for source in files:
        if not isinstance(source, dict) or source.get("kind") != "audio_acb":
            continue
        sheet_name = _cri_sheet_name(source.get("source"))
        streams = source.get("streams") or []
        if not isinstance(streams, list):
            continue
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            validation = stream.get("validation") or {}
            quality = (
                validation.get("quality")
                if isinstance(validation, dict)
                else None
            )
            cue_name = str(stream.get("name") or "")
            if not isinstance(quality, dict):
                warnings.append(
                    "missing audio quality validation: "
                    f"{sheet_name} / {cue_name or '<unnamed>'}"
                )
                continue
            if validation.get("ok") is False:
                if quality.get("status") == "suspicious_decryption":
                    warnings.append(
                        "suspicious decoded audio skipped: "
                        f"{sheet_name} / {cue_name or '<unnamed>'}"
                    )
                continue
            if quality.get("status") == "silent":
                warnings.append(
                    "silent decoded audio skipped: "
                    f"{sheet_name} / {cue_name or '<unnamed>'}"
                )
                continue
            output = _resolve_report_output(
                report_path,
                stream.get("output"),
            )
            if not cue_name or not output.is_file():
                continue
            key = (sheet_name.casefold(), cue_name.casefold())
            index[key].append(
                {
                    "source": str(output),
                    "durationSeconds": float(
                        stream.get("duration_seconds") or 0
                    ),
                    "byteSize": int(stream.get("size") or output.stat().st_size),
                }
            )
    for key, matches in index.items():
        if len(matches) > 1:
            warnings.append(
                "ambiguous decoded audio for "
                f"{key[0]} / {key[1]}: {len(matches)} files"
            )
    return dict(index), warnings


def _sound_evidence(
    sound_id: int,
    sounds: Mapping[int, dict[str, Any]],
    cue_sheets: Mapping[int, dict[str, Any]],
    audio_index: Mapping[tuple[str, str], list[dict[str, Any]]],
    *,
    audio_playback: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if sound_id <= 0:
        return {
            "soundId": sound_id,
            "cueSheetId": None,
            "cueSheetName": "",
            "cueName": "",
            "capabilityState": "metadata_only",
            "audioId": None,
            "audioUrl": None,
            "durationSeconds": 0,
        }, None

    sound = sounds.get(sound_id)
    if not sound:
        return {
            "soundId": sound_id,
            "cueSheetId": None,
            "cueSheetName": "",
            "cueName": "",
            "capabilityState": "missing",
            "audioId": None,
            "audioUrl": None,
            "durationSeconds": 0,
        }, None

    sheet_id = int(sound.get("_soundCueSheetID") or 0)
    sheet = cue_sheets.get(sheet_id)
    cue_name = str(sound.get("_cueName") or "")
    sheet_name = str(sheet.get("_cueSheetName") or "") if sheet else ""
    if not sheet or not cue_name:
        return {
            "soundId": sound_id,
            "cueSheetId": sheet_id or None,
            "cueSheetName": sheet_name,
            "cueName": cue_name,
            "capabilityState": "missing",
            "audioId": None,
            "audioUrl": None,
            "durationSeconds": 0,
        }, None

    matches = audio_index.get(
        (sheet_name.casefold(), cue_name.casefold()),
        [],
    )
    if not matches:
        state = "disabled" if not audio_playback else "metadata_only"
        return {
            "soundId": sound_id,
            "cueSheetId": sheet_id,
            "cueSheetName": sheet_name,
            "cueName": cue_name,
            "capabilityState": state,
            "audioId": None,
            "audioUrl": None,
            "durationSeconds": 0,
        }, None
    if len(matches) > 1:
        return {
            "soundId": sound_id,
            "cueSheetId": sheet_id,
            "cueSheetName": sheet_name,
            "cueName": cue_name,
            "capabilityState": "unsupported",
            "audioId": None,
            "audioUrl": None,
            "durationSeconds": 0,
        }, None

    match = matches[0]
    audio_id = _audio_id(sheet_name, cue_name)
    if not audio_playback:
        return {
            "soundId": sound_id,
            "cueSheetId": sheet_id,
            "cueSheetName": sheet_name,
            "cueName": cue_name,
            "capabilityState": "disabled",
            "audioId": audio_id,
            "audioUrl": None,
            "durationSeconds": match["durationSeconds"],
        }, None
    public_url = f"/media/audio/{audio_id}.flac"
    publication = {
        "id": audio_id,
        "source": match["source"],
        "publicUrl": public_url,
        "durationSeconds": match["durationSeconds"],
        "byteSize": match["byteSize"],
    }
    return {
        "soundId": sound_id,
        "cueSheetId": sheet_id,
        "cueSheetName": sheet_name,
        "cueName": cue_name,
        "capabilityState": "available",
        "audioId": audio_id,
        "audioUrl": public_url,
        "durationSeconds": match["durationSeconds"],
    }, publication


def _audio_capability(
    owner_kind: str,
    owner_id: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "id": _capability_id(owner_id, "audio"),
        "reference": evidence.get("soundId"),
        "role": f"{owner_kind}_audio",
        "containerPath": None,
        "state": evidence.get("capabilityState"),
        "previewUrl": None,
        "originalUrl": evidence.get("audioUrl"),
        "sourceBundle": evidence.get("cueSheetName") or "",
        "sourcePathId": evidence.get("cueName") or "",
        "exportedFile": None,
        "owner": {"kind": owner_kind, "id": owner_id},
    }


def _image_capability(
    owner_kind: str,
    owner_id: str,
    role: str,
    reference: str,
    container: str,
    manifest_record: Mapping[str, Any] | None,
    catalog_asset: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not reference:
        state = "metadata_only"
    elif catalog_asset is not None:
        state = "available"
    elif manifest_record is not None:
        state = "unsupported"
    else:
        state = "metadata_only"
    return {
        "id": _capability_id(owner_id, role),
        "reference": reference or None,
        "role": role,
        "containerPath": container or None,
        "state": state,
        "previewUrl": (
            catalog_asset.get("previewUrl") if catalog_asset else None
        ),
        "originalUrl": (
            catalog_asset.get("originalUrl") if catalog_asset else None
        ),
        "sourceBundle": (
            str(manifest_record.get("bundle") or "")
            if manifest_record
            else str(catalog_asset.get("sourceBundle") or "")
            if catalog_asset
            else ""
        ),
        "sourcePathId": (
            str(manifest_record.get("path_id") or "")
            if manifest_record
            else str(catalog_asset.get("sourceObjectId") or "")
            if catalog_asset
            else ""
        ),
        "exportedFile": (
            str(manifest_record.get("exported_file") or "")
            if manifest_record
            else str(catalog_asset.get("sourcePath") or "")
            if catalog_asset
            else ""
        ),
        "owner": {"kind": owner_kind, "id": owner_id},
    }


def _dedupe_publications(
    publications: Iterable[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for publication in publications:
        if not publication:
            continue
        existing = by_id.get(publication["id"])
        if existing:
            if existing == publication:
                continue
            same_content_address = (
                bool(existing.get("sha256"))
                and existing.get("sha256") == publication.get("sha256")
                and existing.get("publicUrl") == publication.get("publicUrl")
            )
            if same_content_address:
                continue
            raise CharacterMediaError(
                f"media publication {publication['id']} has conflicting files"
            )
        by_id[publication["id"]] = publication
    return [by_id[key] for key in sorted(by_id)]


def _story_friendship_index(
    story_database: Mapping[str, Any],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for entry in story_database.get("entries", []):
        if not isinstance(entry, dict) or entry.get("kind") != "friendship":
            continue
        friendship_id = entry.get("characterFriendshipId")
        entry_id = entry.get("id")
        if isinstance(friendship_id, str) and isinstance(entry_id, str):
            result[friendship_id].append(entry_id)
    return {key: sorted(value) for key, value in result.items()}


def _live2d_runtime_projection(
    report: Mapping[str, Any] | None,
    *,
    release_id: str,
) -> dict[str, Any]:
    """Load one release-scoped adapter decision for shared capabilities."""

    if not isinstance(report, Mapping):
        return {
            "decision": "unassessed",
            "capabilityState": "unsupported",
            "dynamicPlayback": False,
            "representativeModelPath": "",
            "evidencePath": None,
        }
    evidence = report.get("evidence")
    sample = evidence.get("sample") if isinstance(evidence, Mapping) else None
    sample = sample if isinstance(sample, Mapping) else {}
    if sample.get("sourceReleaseId") != release_id:
        return {
            "decision": "unassessed",
            "capabilityState": "unsupported",
            "dynamicPlayback": False,
            "representativeModelPath": "",
            "evidencePath": None,
        }
    decision = report.get("decision")
    update = report.get("capabilityUpdate")
    decision = decision if isinstance(decision, Mapping) else {}
    update = update if isinstance(update, Mapping) else {}
    capability_state = str(update.get("state") or "unsupported")
    if capability_state not in {"experimental", "unsupported"}:
        capability_state = "unsupported"
    return {
        "decision": str(decision.get("conclusion") or "unassessed"),
        "capabilityState": capability_state,
        "dynamicPlayback": bool(decision.get("dynamicPlayback")),
        "representativeModelPath": str(sample.get("modelPath") or ""),
        "evidencePath": update.get("evidencePath"),
    }


def build_character_media(
    master_root: Path,
    master: MasterData,
    manifest_path: Path,
    cri_report_path: Path,
    catalog_assets: list[dict[str, Any]],
    story_database: Mapping[str, Any],
    *,
    release_id: str,
    audio_playback: bool,
    live2d_runtime_report: Mapping[str, Any] | None = None,
) -> CharacterMediaBuild:
    """Build the complete character-media domain in one deterministic pass."""

    tables = {name: _load_table(master_root, name) for name in REQUIRED_TABLES}
    manifest_by_container, manifest_rows = _manifest_records(manifest_path)
    assets_by_container = _catalog_asset_index(catalog_assets)
    decoded_audio, warnings = _audio_index(cri_report_path)
    live2d_runtime = _live2d_runtime_projection(
        live2d_runtime_report,
        release_id=release_id,
    )

    sounds = _unique_index(tables["MasterSound"], "_id", "sound")
    cue_sheets = _unique_index(
        tables["MasterSoundCueSheet"],
        "_id",
        "sound cue sheet",
    )
    known_character_ids = set(master.characters)
    capabilities: list[dict[str, Any]] = []
    publications: list[dict[str, Any] | None] = []
    texture_publications: list[dict[str, Any] | None] = []

    costumes: list[dict[str, Any]] = []
    assigned_texture_containers: set[str] = set()
    for row in tables["MasterCharacterCostume"]:
        master_id = int(row["_id"])
        character_master_id = int(row.get("_characterID") or 0)
        if character_master_id not in known_character_ids:
            raise CharacterMediaError(
                f"costume {master_id} references missing character "
                f"{character_master_id}"
            )
        live2d_path = str(row.get("_live2dPath") or "")
        prefix = (
            "Assets/AddressableResources/Character/Live2D/"
            f"{live2d_path}.2048/"
        )
        model_records = [
            record
            for record in manifest_rows
            if str(record.get("container_path") or "").startswith(prefix)
        ]
        model_state = (
            live2d_runtime["capabilityState"]
            if model_records
            else "metadata_only"
        )
        costume_id = _costume_id(master_id)
        selected_texture_records = _select_texture_records(model_records)
        assigned_texture_containers.update(selected_texture_records)

        texture_candidates: list[dict[str, Any]] = []
        for container, record in sorted(selected_texture_records.items()):
            candidate, publication = _texture_candidate(
                record,
                manifest_root=manifest_path.parent,
                release_id=release_id,
            )
            texture_candidates.append(candidate)
            capabilities.append({
                "id": _capability_id(costume_id, f"texture:{container}"),
                "reference": candidate["id"],
                "role": "costume_texture",
                "containerPath": container,
                "state": candidate["state"],
                "previewUrl": candidate["previewUrl"],
                "originalUrl": None,
                "sourceBundle": candidate["sourceBundle"],
                "sourcePathId": candidate["sourcePathId"],
                "exportedFile": candidate["exportedFile"],
                "owner": {"kind": "costume", "id": costume_id},
            })
            texture_publications.append(publication)

        if any(item["state"] == "available" for item in texture_candidates):
            texture_state = "available"
        elif texture_candidates:
            texture_state = "unsupported"
        else:
            texture_state = "metadata_only"
        representative_sample = (
            bool(live2d_path)
            and live2d_path == live2d_runtime["representativeModelPath"]
        )
        static_fallback = (
            "available"
            if texture_state == "available"
            else "metadata_only"
        )
        capability = {
            "id": _capability_id(costume_id, "live2d_model"),
            "reference": live2d_path or None,
            "role": "live2d_model",
            "containerPath": prefix if live2d_path else None,
            "state": model_state,
            "previewUrl": None,
            "originalUrl": None,
            "sourceBundle": "",
            "sourcePathId": "",
            "exportedFile": None,
            "owner": {"kind": "costume", "id": costume_id},
            "runtimeDecision": live2d_runtime["decision"],
            "dynamicPlayback": live2d_runtime["dynamicPlayback"],
            "staticFallback": static_fallback,
            "runtimeEvidence": {
                "representativeSample": representative_sample,
                "evidencePath": live2d_runtime["evidencePath"],
            },
        }
        capabilities.append(capability)
        costumes.append(
            {
                "id": costume_id,
                "masterId": master_id,
                "characterId": _character_id(character_master_id),
                "costumeNumber": int(row.get("_costumeID") or 0),
                "isDefault": bool(row.get("_isDefault")),
                "live2dPath": live2d_path,
                "modelState": model_state,
                "previewState": "metadata_only",
                "previewAssetId": None,
                "runtimeDecision": live2d_runtime["decision"],
                "dynamicPlayback": live2d_runtime["dynamicPlayback"],
                "representativeRuntimeSample": representative_sample,
                "textureState": texture_state,
                "textureCount": len(texture_candidates),
                "textureCandidates": texture_candidates,
                "relatedTalkIds": [],
                "relatedStoryEntryIds": [],
                "source": {
                    "table": "MasterCharacterCostume",
                    "masterId": master_id,
                },
            }
        )

    all_live2d_texture_records = _select_texture_records(
        record
        for record in manifest_rows
        if str(record.get("container_path") or "").startswith(
            "Assets/AddressableResources/Character/Live2D/"
        )
    )
    unassigned_texture_candidates: list[dict[str, Any]] = []
    for container, record in sorted(all_live2d_texture_records.items()):
        if container in assigned_texture_containers:
            continue
        candidate, publication = _texture_candidate(
            record,
            manifest_root=manifest_path.parent,
            release_id=release_id,
        )
        unassigned_texture_candidates.append(candidate)
        texture_publications.append(publication)
        capabilities.append({
            "id": _capability_id("character-texture-archive", container),
            "reference": candidate["id"],
            "role": "unassigned_costume_texture",
            "containerPath": container,
            "state": candidate["state"],
            "previewUrl": candidate["previewUrl"],
            "originalUrl": None,
            "sourceBundle": candidate["sourceBundle"],
            "sourcePathId": candidate["sourcePathId"],
            "exportedFile": candidate["exportedFile"],
            "owner": {"kind": "archive", "id": "character-textures"},
        })

    costume_by_number_and_character = {
        (item["characterId"], item["costumeNumber"]): item for item in costumes
    }

    voices: list[dict[str, Any]] = []
    for row in tables["MasterCharacterVoice"]:
        master_id = int(row["_id"])
        character_master_id = int(row.get("_characterId") or 0)
        if character_master_id not in known_character_ids:
            raise CharacterMediaError(
                f"voice {master_id} references missing character "
                f"{character_master_id}"
            )
        sound_id = int(row.get("_soundId") or 0)
        evidence, publication = _sound_evidence(
            sound_id,
            sounds,
            cue_sheets,
            decoded_audio,
            audio_playback=audio_playback,
        )
        voice_id = _voice_id(master_id)
        voice_type = int(row.get("_type") or 0)
        text_id = row.get("_textId")
        capabilities.append(_audio_capability("voice", voice_id, evidence))
        publications.append(publication)
        voices.append(
            {
                "id": voice_id,
                "masterId": master_id,
                "characterId": _character_id(character_master_id),
                "typeCode": voice_type,
                "category": VOICE_TYPE_LABELS.get(voice_type, "未分类"),
                "text": _resolve_text(
                    master,
                    text_id,
                    f"语音 {master_id}",
                ),
                "textId": text_id if isinstance(text_id, str) else "",
                "scoreRank": int(row.get("_scoreRank") or 0),
                "startAt": str(row.get("_startAt") or ""),
                **evidence,
                "source": {
                    "table": "MasterCharacterVoice",
                    "masterId": master_id,
                },
            }
        )

    talks: list[dict[str, Any]] = []
    for row in tables["MasterTalk"]:
        master_id = int(row["_id"])
        character_master_id = int(row.get("_characterId") or 0)
        if character_master_id not in known_character_ids:
            raise CharacterMediaError(
                f"talk {master_id} references missing character "
                f"{character_master_id}"
            )
        character_id = _character_id(character_master_id)
        costume_number = int(row.get("_costumeId") or 0)
        costume = costume_by_number_and_character.get(
            (character_id, costume_number)
        )
        sound_id = int(row.get("_voiceSoundId") or 0)
        evidence, publication = _sound_evidence(
            sound_id,
            sounds,
            cue_sheets,
            decoded_audio,
            audio_playback=audio_playback,
        )
        talk_id = _talk_id(master_id)
        text_id = row.get("_textId")
        capabilities.append(_audio_capability("talk", talk_id, evidence))
        publications.append(publication)
        talks.append(
            {
                "id": talk_id,
                "masterId": master_id,
                "characterId": character_id,
                "categoryCode": int(row.get("_category") or 0),
                "text": _resolve_text(master, text_id, f"主页台词 {master_id}"),
                "textId": text_id if isinstance(text_id, str) else "",
                "costumeId": costume["id"] if costume else None,
                "costumeNumber": costume_number,
                "motionName": str(row.get("_motionName") or ""),
                "expressionName": str(row.get("_expressionName") or ""),
                "year": int(row.get("_year") or 0),
                "seasonStartAt": str(row.get("_seasonStartAt") or ""),
                "seasonEndAt": str(row.get("_seasonEndAt") or ""),
                "birthdayCharacterId": (
                    _character_id(int(row["_birthdayCharacterId"]))
                    if int(row.get("_birthdayCharacterId") or 0)
                    else None
                ),
                "unlockCharacterRank": int(
                    row.get("_unlockCharacterRank") or 0
                ),
                **evidence,
                "source": {
                    "table": "MasterTalk",
                    "masterId": master_id,
                },
            }
        )
        if costume:
            costume["relatedTalkIds"].append(talk_id)

    friendship_story_ids = _story_friendship_index(story_database)
    live_dialogues_by_pair: dict[tuple[int, int], list[str]] = defaultdict(list)
    live_dialogues: list[dict[str, Any]] = []
    for row in tables["MasterLiveDialogueFixedPair"]:
        master_id = int(row["_id"])
        left_id = int(row.get("_characterID01") or 0)
        right_id = int(row.get("_characterID02") or 0)
        if left_id not in known_character_ids or right_id not in known_character_ids:
            warnings.append(
                f"fixed-pair live dialogue {master_id} references unknown "
                f"characters {left_id}, {right_id}"
            )
            continue
        dialogue_id = _live_dialogue_id(master_id)
        pair_key = tuple(sorted((left_id, right_id)))
        live_dialogues_by_pair[pair_key].append(dialogue_id)
        live_dialogues.append(
            {
                "id": dialogue_id,
                "masterId": master_id,
                "dialogueType": int(row.get("_dialogueType") or 0),
                "characterIds": [
                    _character_id(left_id),
                    _character_id(right_id),
                ],
                "unlockFriendshipRank": int(
                    row.get("_unlockFriendshipRank") or 0
                ),
                "lines": [
                    {
                        "characterId": _character_id(left_id),
                        "text": _resolve_text(
                            master,
                            row.get("_character01ComboVoiceTextID"),
                            "",
                        ),
                        "soundId": int(
                            row.get("_character01ComboVoiceSoundID") or 0
                        ),
                    },
                    {
                        "characterId": _character_id(right_id),
                        "text": _resolve_text(
                            master,
                            row.get("_character02ComboVoiceTextID"),
                            "",
                        ),
                        "soundId": int(
                            row.get("_character02ComboVoiceSoundID") or 0
                        ),
                    },
                ],
                "source": {
                    "table": "MasterLiveDialogueFixedPair",
                    "masterId": master_id,
                },
            }
        )

    friendship_ranks = [
        {
            "rank": int(row.get("_rank") or 0),
            "exp": int(row.get("_exp") or 0),
        }
        for row in sorted(
            tables["MasterCharacterFriendshipRank"],
            key=lambda item: int(item.get("_rank") or 0),
        )
    ]
    friendships: list[dict[str, Any]] = []
    for row in tables["MasterCharacterFriendship"]:
        master_id = int(row["_id"])
        left_id = int(row.get("_masterCharacterIdA") or 0)
        right_id = int(row.get("_masterCharacterIdB") or 0)
        if left_id not in known_character_ids or right_id not in known_character_ids:
            raise CharacterMediaError(
                f"friendship {master_id} references missing characters "
                f"{left_id}, {right_id}"
            )
        friendship_id = _friendship_id(master_id)
        banner_name = str(row.get("_storyBanner") or "")
        banner_container = (
            "Assets/AddressableResources/Story/Banner/Friendship/"
            f"{banner_name}.png"
        )
        banner_capability = _image_capability(
            "friendship",
            friendship_id,
            "friendship_banner",
            banner_name,
            banner_container,
            manifest_by_container.get(banner_container),
            assets_by_container.get(banner_container),
        )
        capabilities.append(banner_capability)
        pair_key = tuple(sorted((left_id, right_id)))
        friendships.append(
            {
                "id": friendship_id,
                "masterId": master_id,
                "characterIds": [
                    _character_id(left_id),
                    _character_id(right_id),
                ],
                "bannerReference": banner_name,
                "bannerCapability": banner_capability,
                "ranks": friendship_ranks,
                "storyEntryIds": friendship_story_ids.get(
                    friendship_id,
                    [],
                ),
                "liveDialogueIds": sorted(
                    live_dialogues_by_pair.get(pair_key, [])
                ),
                "source": {
                    "table": "MasterCharacterFriendship",
                    "masterId": master_id,
                },
            }
        )

    media_items: list[dict[str, Any]] = []
    portrait_roles = (
        ("character_sprite", "角色立绘"),
        ("character_thumbnail", "角色缩略图"),
    )
    for character_master_id in sorted(known_character_ids):
        for order, (reference, label) in enumerate(portrait_roles):
            container = (
                "Assets/AddressableResources/Character/Image/"
                f"{character_master_id}/{reference}.png"
            )
            asset = assets_by_container.get(container)
            if not asset:
                continue
            media_id = (
                f"character-media-portrait-{character_master_id}-{reference}"
            )
            capability = _image_capability(
                "character_media",
                media_id,
                "character_portrait",
                reference,
                container,
                manifest_by_container.get(container),
                asset,
            )
            capabilities.append(capability)
            media_items.append({
                "id": media_id,
                "masterId": character_master_id,
                "kind": "portrait",
                "title": label,
                "characterIds": [_character_id(character_master_id)],
                "bandIds": [],
                "assetId": asset.get("id"),
                "reference": reference,
                "containerPath": container,
                "fit": "contain",
                "order": order,
                "startAt": "",
                "endAt": "",
                "capabilityState": capability["state"],
                "previewUrl": capability["previewUrl"],
                "source": {
                    "table": "MasterCharacter",
                    "masterId": character_master_id,
                },
            })
    for row in tables["MasterLoadingComics"]:
        master_id = int(row["_id"])
        reference = str(row.get("_imageAsset") or "")
        container = (
            "Assets/AddressableResources/Image/Comic/"
            f"{reference}.png"
        )
        media_id = _media_id("comic", master_id)
        capability = _image_capability(
            "character_media",
            media_id,
            "comic_image",
            reference,
            container,
            manifest_by_container.get(container),
            assets_by_container.get(container),
        )
        capabilities.append(capability)
        media_items.append(
            {
                "id": media_id,
                "masterId": master_id,
                "kind": "comic",
                "title": f"加载漫画 {master_id}",
                "characterIds": [
                    _character_id(int(value))
                    for value in row.get("_characterIds") or []
                    if isinstance(value, int) and value in known_character_ids
                ],
                "bandIds": [],
                "assetId": (
                    assets_by_container.get(container, {}).get("id")
                ),
                "reference": reference,
                "containerPath": container,
                "fit": "contain",
                "order": int(row.get("_order") or 0),
                "startAt": str(row.get("_startAt") or ""),
                "endAt": str(row.get("_endAt") or ""),
                "capabilityState": capability["state"],
                "previewUrl": capability["previewUrl"],
                "source": {
                    "table": "MasterLoadingComics",
                    "masterId": master_id,
                },
            }
        )

    for row in tables["MasterStamp"]:
        master_id = int(row["_id"])
        reference = str(row.get("_stampAsset") or "")
        container = (
            f"Assets/AddressableResources/{reference}.png"
            if reference
            else ""
        )
        media_id = _media_id("stamp", master_id)
        capability = _image_capability(
            "character_media",
            media_id,
            "stamp_image",
            reference,
            container,
            manifest_by_container.get(container),
            assets_by_container.get(container),
        )
        capabilities.append(capability)
        text_id = row.get("_nameTextId")
        media_items.append(
            {
                "id": media_id,
                "masterId": master_id,
                "kind": "stamp",
                "title": _resolve_text(master, text_id, f"角色贴图 {master_id}"),
                "characterIds": [
                    _character_id(int(value))
                    for value in row.get("_characterIds") or []
                    if isinstance(value, int) and value in known_character_ids
                ],
                "bandIds": [],
                "assetId": (
                    assets_by_container.get(container, {}).get("id")
                    if container
                    else None
                ),
                "reference": reference,
                "containerPath": container or None,
                "fit": "square",
                "order": int(row.get("_priority") or 0),
                "startAt": str(row.get("_startAt") or ""),
                "endAt": str(row.get("_endAt") or ""),
                "capabilityState": capability["state"],
                "previewUrl": capability["previewUrl"],
                "source": {
                    "table": "MasterStamp",
                    "masterId": master_id,
                },
            }
        )

    for chapter in story_database.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        character_ids = list(chapter.get("mainCharacterIds") or [])
        band_ids = [chapter["bandId"]] if chapter.get("bandId") else []
        for role, capability in (chapter.get("capabilities") or {}).items():
            if not isinstance(capability, dict):
                continue
            container = str(capability.get("containerPath") or "")
            asset = assets_by_container.get(container)
            if not asset:
                continue
            source_key = f"{chapter.get('id')}:{role}"
            media_id = (
                "character-media-story-"
                f"{_compact_hash(source_key)}"
            )
            media_items.append(
                {
                    "id": media_id,
                    "masterId": int(chapter.get("masterId") or 0),
                    "kind": "story_image",
                    "title": f"{chapter.get('name') or '剧情'} · {role}",
                    "characterIds": character_ids,
                    "bandIds": band_ids,
                    "assetId": asset.get("id"),
                    "reference": capability.get("reference"),
                    "containerPath": container,
                    "fit": "wide",
                    "order": 0,
                    "startAt": str(chapter.get("startAt") or ""),
                    "endAt": str(chapter.get("endAt") or ""),
                    "capabilityState": capability.get("state") or "available",
                    "previewUrl": asset.get("previewUrl"),
                    "source": {
                        "table": "story-database",
                        "masterId": int(chapter.get("masterId") or 0),
                    },
                }
            )

    for costume in costumes:
        costume["relatedTalkIds"].sort()

    voice_by_character: dict[str, list[str]] = defaultdict(list)
    talk_by_character: dict[str, list[str]] = defaultdict(list)
    costume_by_character: dict[str, list[str]] = defaultdict(list)
    friendship_by_character: dict[str, list[str]] = defaultdict(list)
    media_by_character: dict[str, list[str]] = defaultdict(list)
    for voice in voices:
        voice_by_character[voice["characterId"]].append(voice["id"])
    for talk in talks:
        talk_by_character[talk["characterId"]].append(talk["id"])
    for costume in costumes:
        costume_by_character[costume["characterId"]].append(costume["id"])
    for friendship in friendships:
        for character_id in friendship["characterIds"]:
            friendship_by_character[character_id].append(friendship["id"])
    for media in media_items:
        for character_id in media["characterIds"]:
            media_by_character[character_id].append(media["id"])

    projections: list[dict[str, Any]] = []
    for master_id in sorted(known_character_ids):
        character_id = _character_id(master_id)
        costume_ids = sorted(costume_by_character.get(character_id, []))
        voice_ids = sorted(voice_by_character.get(character_id, []))
        talk_ids = sorted(talk_by_character.get(character_id, []))
        friendship_ids = sorted(friendship_by_character.get(character_id, []))
        media_ids = sorted(media_by_character.get(character_id, []))
        projections.append(
            {
                "characterId": character_id,
                "costumeIds": costume_ids,
                "voiceIds": voice_ids,
                "talkIds": talk_ids,
                "friendshipIds": friendship_ids,
                "mediaItemIds": media_ids,
                "counts": {
                    "costumes": len(costume_ids),
                    "voices": len(voice_ids),
                    "talks": len(talk_ids),
                    "friendships": len(friendship_ids),
                    "media": len(media_ids),
                },
            }
        )

    search_index = {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "records": [
            *[
                {
                    "id": voice["id"],
                    "kind": "voice",
                    "characterId": voice["characterId"],
                    "category": voice["category"],
                    "text": voice["text"],
                    "searchableText": (
                        f"{voice['category']} {voice['text']} "
                        f"{voice['cueName']}"
                    ),
                    "capabilityState": voice["capabilityState"],
                }
                for voice in voices
            ],
            *[
                {
                    "id": talk["id"],
                    "kind": "talk",
                    "characterId": talk["characterId"],
                    "category": "主页台词",
                    "text": talk["text"],
                    "searchableText": (
                        f"{talk['text']} {talk['motionName']} "
                        f"{talk['expressionName']}"
                    ),
                    "capabilityState": talk["capabilityState"],
                }
                for talk in talks
            ],
        ],
    }

    state_counts: dict[str, int] = defaultdict(int)
    for capability in capabilities:
        state_counts[str(capability["state"])] += 1
    voice_state_counts: dict[str, int] = defaultdict(int)
    for voice in voices:
        voice_state_counts[str(voice["capabilityState"])] += 1
    talk_state_counts: dict[str, int] = defaultdict(int)
    for talk in talks:
        talk_state_counts[str(talk["capabilityState"])] += 1
    texture_state_counts: dict[str, int] = defaultdict(int)
    preview_state_counts: dict[str, int] = defaultdict(int)
    for costume in costumes:
        texture_state_counts[str(costume["textureState"])] += 1
        preview_state_counts[str(costume["previewState"])] += 1
    quality = {
        "costumeCount": len(costumes),
        "voiceCount": len(voices),
        "talkCount": len(talks),
        "friendshipCount": len(friendships),
        "liveDialogueCount": len(live_dialogues),
        "mediaItemCount": len(media_items),
        "portraitCount": sum(
            item["kind"] == "portrait" for item in media_items
        ),
        "textureCandidateCount": sum(
            costume["textureCount"] for costume in costumes
        ),
        "unassignedTextureCandidateCount": len(
            unassigned_texture_candidates
        ),
        "textureStateCounts": dict(sorted(texture_state_counts.items())),
        "costumePreviewStateCounts": dict(sorted(preview_state_counts.items())),
        "voiceStateCounts": dict(sorted(voice_state_counts.items())),
        "talkStateCounts": dict(sorted(talk_state_counts.items())),
        "capabilityCounts": dict(sorted(state_counts.items())),
    }
    database = {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "audioPlayback": audio_playback,
        "costumes": costumes,
        "unassignedTextureCandidates": unassigned_texture_candidates,
        "voices": voices,
        "talks": talks,
        "friendships": friendships,
        "liveDialogues": live_dialogues,
        "mediaItems": media_items,
        "quality": quality,
    }
    quality_report = {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        **quality,
        "warnings": warnings,
    }
    return CharacterMediaBuild(
        database=database,
        projections={
            "schemaVersion": 1,
            "sourceReleaseId": release_id,
            "characters": projections,
        },
        search_index=search_index,
        quality_report=quality_report,
        capabilities=sorted(capabilities, key=lambda item: item["id"]),
        audio_publications=_dedupe_publications(publications),
        texture_publications=_dedupe_publications(texture_publications),
        warnings=warnings,
    )
