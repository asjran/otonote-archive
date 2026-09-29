"""Parse ADV script shards and decide whether a story reader can publish.

The current extraction only contains the tutorial ADV shards (Text, Sound,
SoundCueSheet, Video) and those shards are localized strings tables — they
are not the runtime command timeline that drives the player. The adapter
recognizes the four shard kinds, refuses to invent a reader when the Text
shard is missing, and refuses to publish unsupported shards. It records
every unknown command it encounters so quality reports stay honest.

JSON corruption in a shard whose container is declared in the manifest is
treated as a build-level error so the publish pipeline cannot silently
ship a broken reader.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


SHARD_KINDS = ("Text", "Sound", "SoundCueSheet", "Video")

ADV_CONTAINER_PATTERN = re.compile(
    r"^Assets/AddressableResources/Adv/Episode/(?P<adv>[^/]+)/"
    r"(?P<adv_id>[^/]+)-(?P<shard>Text|Sound|SoundCueSheet|Video)\.txt$"
)


class AdvAdapterError(ValueError):
    """Raised when an ADV shard is declared but unreadable."""


@dataclass(frozen=True)
class AdvDocument:
    adv_id: str
    adv_master_id: int
    shard_states: dict[str, str]
    locale_lines: list[dict[str, Any]]
    lines: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    unknown_commands: list[dict[str, Any]]
    parse_status: str
    raw_summary: dict[str, Any]
    referenced_assets: dict[str, list[str]]


@dataclass(frozen=True)
class AdvAdapterBuild:
    documents: dict[str, AdvDocument]
    per_adv_status: dict[int, dict[str, str]]
    warnings: list[str]
    search_lines: list[dict[str, Any]] = field(default_factory=list)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise AdvAdapterError(f"manifest not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _index_manifest(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_container: dict[str, dict[str, Any]] = {}
    for record in manifest.get("assets", []):
        if not isinstance(record, dict):
            continue
        container = str(record.get("container_path") or "")
        if not container:
            continue
        if container not in by_container:
            by_container[container] = record
    return by_container


def _shard_container(adv_identifier: str, shard: str) -> str:
    return (
        f"Assets/AddressableResources/Adv/Episode/"
        f"{adv_identifier}/{adv_identifier}-{shard}.txt"
    )


def _resolve_shard(
    *,
    adv_identifier: str,
    shard: str,
    manifest_index: Mapping[str, dict[str, Any]],
    extracted_root: Path,
    warnings: list[str],
    build_errors: list[AdvAdapterError],
    adv_id: str,
) -> dict[str, Any]:
    container = _shard_container(adv_identifier, shard)
    record = manifest_index.get(container)
    if not record:
        return {
            "kind": shard,
            "state": "missing",
            "containerPath": container,
            "exportedFile": None,
            "absolutePath": None,
            "parsed": False,
            "rows": 0,
            "error": None,
        }
    exported = record.get("exported_file")
    if not exported:
        return {
            "kind": shard,
            "state": "missing",
            "containerPath": container,
            "exportedFile": None,
            "absolutePath": None,
            "parsed": False,
            "rows": 0,
            "error": None,
        }
    file_path = extracted_root / str(exported)
    if not file_path.is_file():
        warnings.append(
            f"{adv_id} declares {shard} shard at {container} "
            f"but file is missing: {exported}"
        )
        return {
            "kind": shard,
            "state": "missing",
            "containerPath": container,
            "exportedFile": str(exported),
            "absolutePath": None,
            "parsed": False,
            "rows": 0,
            "error": None,
        }
    try:
        payload = _load_json(file_path)
    except json.JSONDecodeError as exc:
        error = AdvAdapterError(
            f"{adv_id} {shard} shard is corrupt JSON ({file_path}): {exc}"
        )
        build_errors.append(error)
        return {
            "kind": shard,
            "state": "unsupported",
            "containerPath": container,
            "exportedFile": str(exported),
            "absolutePath": str(file_path),
            "parsed": False,
            "rows": 0,
            "error": str(exc),
        }

    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("_allData"), list):
        rows = [row for row in payload["_allData"] if isinstance(row, dict)]

    return {
        "kind": shard,
        "state": "present",
        "containerPath": container,
        "exportedFile": str(exported),
        "absolutePath": str(file_path),
        "parsed": True,
        "rows": len(rows),
        "error": None,
    }


def _locale_lines_from_text(
    shard: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Best-effort locale-line extraction for unsupported shards."""

    if not shard["parsed"] or not shard.get("absolutePath"):
        return []
    try:
        payload = _load_json(Path(str(shard["absolutePath"])))
    except (json.JSONDecodeError, OSError):
        return []
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "id": row.get("_id"),
            "japanese": row.get("_japanese") or "",
            "english": row.get("_english") or "",
            "simplifiedChinese": row.get("_simplifiedChinese") or "",
            "traditionalChinese": row.get("_traditionalChinese") or "",
        }
        for row in rows
        if isinstance(row, dict) and row.get("_id")
    ]


def _public_shard_states(
    shard_states: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Project extraction internals onto the shared capability vocabulary."""

    return {
        key: "available" if state["state"] == "present" else state["state"]
        for key, state in shard_states.items()
    }


def _looks_like_command_timeline(rows: Iterable[Mapping[str, Any]]) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        command_keys = {
            key for key in row.keys()
            if isinstance(key, str) and key.startswith("_")
        }
        if {"_commandType", "_command", "_type", "_sceneId"} & command_keys:
            return True
    return False


def parse_adv(
    *,
    adv_master_id: int,
    adv_identifier: str,
    manifest_index: Mapping[str, dict[str, Any]],
    extracted_root: Path,
) -> AdvDocument:
    """Parse one ADV by identifier (typically ``_sheetName``)."""

    warnings: list[str] = []
    build_errors: list[AdvAdapterError] = []
    shard_states: dict[str, dict[str, Any]] = {}
    for shard in SHARD_KINDS:
        shard_states[shard] = _resolve_shard(
            adv_identifier=adv_identifier,
            shard=shard,
            manifest_index=manifest_index,
            extracted_root=extracted_root,
            warnings=warnings,
            build_errors=build_errors,
            adv_id=adv_identifier,
        )
    if build_errors:
        raise build_errors[0]

    text_state = shard_states["Text"]
    if text_state["state"] == "missing":
        return AdvDocument(
            adv_id=f"adv-{adv_master_id}",
            adv_master_id=adv_master_id,
            shard_states=_public_shard_states(shard_states),
            locale_lines=[],
            lines=[],
            scenes=[],
            unknown_commands=[],
            parse_status="metadata_only",
            raw_summary={"shardRows": {k: v["rows"] for k, v in shard_states.items()}},
            referenced_assets={
                shard: [state["containerPath"]] if state["state"] != "missing" else []
                for shard, state in shard_states.items()
            },
        )

    if not text_state["parsed"]:
        return AdvDocument(
            adv_id=f"adv-{adv_master_id}",
            adv_master_id=adv_master_id,
            shard_states=_public_shard_states(shard_states),
            locale_lines=[],
            lines=[],
            scenes=[],
            unknown_commands=[],
            parse_status="unsupported",
            raw_summary={
                "shardRows": {k: v["rows"] for k, v in shard_states.items()},
                "textError": text_state.get("error"),
            },
            referenced_assets={
                shard: [state["containerPath"]] if state["state"] == "present" else []
                for shard, state in shard_states.items()
            },
        )

    text_payload = _load_json(extracted_root / str(text_state["exportedFile"]))
    text_rows = text_payload.get("_allData") if isinstance(text_payload, dict) else None
    text_rows = text_rows if isinstance(text_rows, list) else []

    if not _looks_like_command_timeline(text_rows):
        return AdvDocument(
            adv_id=f"adv-{adv_master_id}",
            adv_master_id=adv_master_id,
            shard_states=_public_shard_states(shard_states),
            locale_lines=_locale_lines_from_text(text_state),
            lines=[],
            scenes=[],
            unknown_commands=[],
            parse_status="unsupported",
            raw_summary={
                "shardRows": {k: v["rows"] for k, v in shard_states.items()},
                "reason": (
                    "Text shard contains a localized strings table, "
                    "not a command timeline."
                ),
            },
            referenced_assets={
                shard: [state["containerPath"]] if state["state"] == "present" else []
                for shard, state in shard_states.items()
            },
        )

    raise AdvAdapterError(
        f"{adv_identifier} command timeline parser is not implemented yet"
    )


def build_adv_database(
    manifest_path: Path,
    extracted_root: Path,
    story_entries: Iterable[Mapping[str, Any]],
) -> AdvAdapterBuild:
    """Walk every story entry's ADV and decide what to publish."""

    manifest = _load_manifest(manifest_path)
    manifest_index = _index_manifest(manifest)
    warnings: list[str] = []
    documents: dict[str, AdvDocument] = {}
    per_adv_status: dict[int, dict[str, str]] = {}
    search_lines: list[dict[str, Any]] = []

    seen_identifiers: set[str] = set()
    for entry in story_entries:
        adv = entry.get("adv") or {}
        adv_master_id = adv.get("masterId")
        if not isinstance(adv_master_id, int) or adv_master_id <= 0:
            continue
        identifier = adv.get("sheetName") or adv.get("episodeAsset") or ""
        if not identifier:
            per_adv_status[adv_master_id] = {"state": "metadata_only"}
            continue
        if identifier in seen_identifiers:
            continue
        seen_identifiers.add(identifier)
        try:
            document = parse_adv(
                adv_master_id=adv_master_id,
                adv_identifier=identifier,
                manifest_index=manifest_index,
                extracted_root=extracted_root,
            )
        except AdvAdapterError as exc:
            raise AdvAdapterError(
                f"ADV {adv_master_id} ({identifier}) failed to parse: {exc}"
            ) from exc
        documents[document.adv_id] = document
        per_adv_status[adv_master_id] = {
            "state": document.parse_status,
            "shards": document.shard_states,
        }
        warnings.extend(document.raw_summary.get("warnings", []))
        if document.parse_status == "available" and document.lines:
            for line in document.lines:
                search_lines.append(line)

    return AdvAdapterBuild(
        documents=documents,
        per_adv_status=per_adv_status,
        warnings=warnings,
        search_lines=search_lines,
    )
