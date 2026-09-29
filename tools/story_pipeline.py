"""Combine story normalization, media capabilities, and ADV scripts into
the four artifacts the site consumes.

Outputs (paths resolved by the caller):

* ``story-database.json`` — chapters, entries, ADV shard states, and the
  shared media capability index (also exposed separately as
  ``media-capabilities.json``).
* ``story-search-index.json`` — searchable chapter/episode text plus any
  lines from successfully parsed ADV scripts.
* ``story-quality-report.json`` — counts, dangling references, and
  capability distribution; never linked from the page tree.

The page layer never touches ``phone_dump`` directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.adv_adapter import build_adv_database
from tools.media_capabilities import build_media_capabilities
from tools.master_catalog import MasterData
from tools.resource_pipeline.localization import resolve_localized_text
from tools.story_catalog import (
    StoryCatalogBuild,
    build_story_catalog,
)


@dataclass(frozen=True)
class StoryPipelineBuild:
    database: dict[str, Any]
    search_index: dict[str, Any]
    quality_report: dict[str, Any]
    media_capabilities: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_master_text(master_root: Path) -> Mapping[str, dict[str, Any]]:
    path = master_root / "MasterText.json"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        row["_id"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("_id"), str)
    }


def _resolve_text(
    texts: Mapping[str, dict[str, Any]],
    text_id: Any,
) -> str:
    if not isinstance(text_id, str) or not text_id:
        return ""
    row = texts.get(text_id)
    if not row:
        return ""
    return resolve_localized_text(row, "zh-CN").text


def _entry_capabilities(
    entry_id: str,
    capability_index: Mapping[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        role: capability
        for role, capability in (
            ("banner", capability_index.get(("entry", entry_id, "episode_banner"))),
            ("image", capability_index.get(("entry", entry_id, "episode_image"))),
            (
                "thumbnail",
                capability_index.get(("entry", entry_id, "thumbnail")),
            ),
        )
        if capability is not None
    }


def _chapter_capabilities(
    chapter_id: str,
    capability_index: Mapping[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    return {
        role: capability
        for role, capability in (
            (
                "banner",
                capability_index.get(("chapter", chapter_id, "chapter_banner")),
            ),
            (
                "image",
                capability_index.get(("chapter", chapter_id, "chapter_image")),
            ),
            (
                "icon",
                capability_index.get(("chapter", chapter_id, "chapter_icon")),
            ),
        )
        if capability is not None
    }


def _capability_index(
    capabilities: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for capability in capabilities:
        owner = capability.get("owner") or {}
        kind = owner.get("kind")
        owner_id = owner.get("id")
        role = capability.get("role")
        if not (kind and owner_id and role):
            continue
        index[(kind, owner_id, role)] = dict(capability)
    return index


def _public_capability(capability: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not capability:
        return None
    return {
        "id": capability.get("id"),
        "state": capability.get("state"),
        "reference": capability.get("reference"),
        "containerPath": capability.get("containerPath"),
        "previewUrl": capability.get("previewUrl"),
        "originalUrl": capability.get("originalUrl"),
    }


def _adv_runtime_projection(
    report: Mapping[str, Any] | None,
    *,
    release_id: str,
    adv_master_id: int,
) -> dict[str, Any] | None:
    if not isinstance(report, Mapping):
        return None
    evidence = report.get("evidence")
    decision = report.get("decision")
    capability = report.get("capabilityUpdate")
    if not all(isinstance(item, Mapping) for item in (evidence, decision, capability)):
        return None
    sample = evidence.get("sample")
    ast = evidence.get("storyAstCandidate")
    root = evidence.get("root")
    if not all(isinstance(item, Mapping) for item in (sample, ast, root)):
        return None
    if sample.get("sourceReleaseId") != release_id:
        return None
    if sample.get("advMasterId") != adv_master_id:
        return None
    return {
        "decision": str(decision.get("conclusion") or "unsupported"),
        "capabilityState": str(capability.get("state") or "unsupported"),
        "readerEnabled": bool(decision.get("readerEnabled")),
        "commandCount": int(root.get("commandCount") or 0),
        "storyAstNodeCount": int(ast.get("nodeCount") or 0),
        "storyAstNodeTypeCounts": dict(ast.get("nodeTypeCounts") or {}),
        "blockers": [str(item) for item in decision.get("blockers", [])],
        "limitations": [str(item) for item in decision.get("limitations", [])],
        "gates": dict(decision.get("gates") or {}),
        "evidencePath": str(capability.get("evidencePath") or ""),
        "sourceReleaseId": release_id,
    }


def _localized_runtime_text(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in (
        "simplifiedChinese",
        "traditionalChinese",
        "japanese",
        "english",
    ):
        text = value.get(key)
        if isinstance(text, str) and text:
            return text
    return ""


def _experimental_runtime_document(
    report: Mapping[str, Any] | None,
    *,
    release_id: str,
    adv_master_id: int,
) -> dict[str, Any] | None:
    """Project verified root commands into the minimum linear reader model.

    This intentionally does not claim original ADV presentation parity.  The
    command order and confirmed enum drive a deterministic text-first flow;
    unavailable background, character, or audio media stay as nullable hooks.
    """

    if not isinstance(report, Mapping):
        return None
    evidence = report.get("evidence")
    decision = report.get("decision")
    if not isinstance(evidence, Mapping) or not isinstance(decision, Mapping):
        return None
    sample = evidence.get("sample")
    ast = evidence.get("storyAstCandidate")
    if not isinstance(sample, Mapping) or not isinstance(ast, Mapping):
        return None
    if sample.get("sourceReleaseId") != release_id:
        return None
    if sample.get("advMasterId") != adv_master_id:
        return None
    gates = decision.get("gates")
    if (
        decision.get("conclusion") != "experimental"
        or decision.get("readerEnabled") is not True
        or not isinstance(gates, Mapping)
        or gates.get("commandEnumConfirmed") is not True
    ):
        return None

    localized = evidence.get("localizedText")
    localized = localized if isinstance(localized, Mapping) else {}
    sounds = evidence.get("sounds")
    sounds = sounds if isinstance(sounds, Mapping) else {}
    raw_nodes = ast.get("nodes")
    nodes = [dict(item) for item in raw_nodes or [] if isinstance(item, Mapping)]
    nodes.sort(key=lambda item: int(item.get("sourceIndex") or 0))

    voices_by_index: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if node.get("type") != "PlayVoice":
            continue
        source_index = int(node.get("sourceIndex") or 0)
        voice_ref = node.get("voiceRef")
        sound = sounds.get(str(voice_ref))
        sound = sound if isinstance(sound, Mapping) else {}
        voices_by_index[source_index] = {
            "voiceRef": voice_ref,
            "cueName": str(sound.get("cueName") or ""),
            "cueSheetName": str(sound.get("cueSheetName") or ""),
            "state": "metadata_only",
            "url": None,
        }

    background_ref: str | None = None
    character_assets: dict[str, str] = {}
    visible_characters: set[str] = set()
    expressions: dict[str, str] = {}
    motions: dict[str, str] = {}
    scenes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    unknown_commands: list[dict[str, Any]] = []

    def ensure_scene(source_index: int) -> int:
        if not scenes or scenes[-1].get("backgroundRef") != background_ref:
            scenes.append({
                "index": len(scenes),
                "sourceIndex": source_index,
                "backgroundRef": background_ref,
                "backgroundState": "metadata_only" if background_ref else "missing",
                "backgroundUrl": None,
            })
        return int(scenes[-1]["index"])

    for node in nodes:
        node_type = str(node.get("type") or "UnknownCommand")
        source_index = int(node.get("sourceIndex") or 0)
        character_ref = str(node.get("characterRef") or "")
        events.append({**node, "sourceIndex": source_index})
        if node_type == "SetCharacterModel" and character_ref:
            asset_ref = str(node.get("assetRef") or "")
            if asset_ref:
                character_assets[character_ref] = asset_ref
        elif node_type == "SetBackground":
            background_ref = str(node.get("assetRef") or "") or None
            ensure_scene(source_index)
        elif node_type == "CharacterEnter" and character_ref:
            visible_characters.add(character_ref)
        elif node_type == "SetExpression" and character_ref:
            expressions[character_ref] = str(node.get("expressionRef") or "")
        elif node_type == "PlayMotion" and character_ref:
            motions[character_ref] = str(node.get("motionRef") or "")
        elif node_type == "Dialogue":
            text_ref = str(node.get("textRef") or "")
            speaker_refs = [
                str(item) for item in node.get("speakerTextRefs", []) if item
            ]
            text = _localized_runtime_text(localized.get(text_ref))
            if not text:
                # Missing media must not block text, but an unresolved text id
                # is diagnostics rather than publishable body copy.
                unknown_commands.append({
                    **node,
                    "reason": "localized text reference is unresolved",
                })
                continue
            lines.append({
                "id": f"runtime-line-{source_index}",
                "order": len(lines),
                "sourceIndex": source_index,
                "sceneIndex": ensure_scene(source_index),
                "speakerId": speaker_refs[0] if speaker_refs else None,
                "speaker": (
                    _localized_runtime_text(localized.get(speaker_refs[0]))
                    if speaker_refs else character_ref
                ),
                "textRef": text_ref,
                "text": text,
                "characterRef": character_ref or None,
                "characterAssetRef": character_assets.get(character_ref),
                "characterVisible": character_ref in visible_characters,
                "expressionRef": expressions.get(character_ref),
                "motionRef": motions.get(character_ref),
                "backgroundRef": background_ref,
                "backgroundState": "metadata_only" if background_ref else "missing",
                "backgroundUrl": None,
                "audio": voices_by_index.get(source_index),
            })
        elif node_type == "UnknownCommand":
            unknown_commands.append(node)

    if not lines:
        return None
    return {
        "parseStatus": "experimental",
        "scenes": scenes,
        "lines": lines,
        "events": events,
        "unknownCommands": unknown_commands,
        "limitations": [str(item) for item in decision.get("limitations", [])],
    }


def _build_search_index(
    chapters: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    texts: Mapping[str, dict[str, Any]],
    adv_documents: Mapping[str, Any],
    runtime_documents: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    runtime_documents = runtime_documents or {}
    chapter_records: list[dict[str, Any]] = []
    for chapter in chapters:
        name = chapter.get("name") or ""
        description = chapter.get("description") or ""
        chapter_records.append(
            {
                "id": chapter["id"],
                "kind": "chapter",
                "title": name,
                "summary": description,
                "spoiler": bool(description),
                "searchableText": " ".join(
                    value for value in (name, description) if value
                ),
            }
        )

    entry_records: list[dict[str, Any]] = []
    for entry in entries:
        adv = entry.get("adv") or {}
        adv_master_id = adv.get("masterId")
        adv_document = adv_documents.get(f"adv-{adv_master_id}") if adv_master_id else None
        runtime_document = (
            runtime_documents.get(f"adv-{adv_master_id}") if adv_master_id else None
        )
        title = _resolve_text(texts, adv.get("titleTextId")) if adv else ""
        description = entry.get("description") or ""
        summary = title or description
        if runtime_document:
            line_count = len(runtime_document.get("lines") or [])
        elif adv_document and adv_document.parse_status == "available":
            line_count = len(adv_document.lines)
        else:
            line_count = 0
        entry_records.append(
            {
                "id": entry["id"],
                "kind": entry["kind"],
                "title": title,
                "episodeNumber": entry.get("episodeNumber") or 0,
                "chapterId": entry.get("chapterId"),
                "summary": summary,
                "spoiler": bool(summary),
                "searchableText": " ".join(
                    value for value in (title, description) if value
                ),
                "lineCount": line_count,
                "parseStatus": (
                    runtime_document.get("parseStatus")
                    if runtime_document
                    else adv_document.parse_status if adv_document else "metadata_only"
                ),
                "characterIds": entry.get("primaryCharacterIds") or [],
                "characterCombination": entry.get("characterCombination") or [],
                "locationId": entry.get("locationId"),
            }
        )

    line_records: list[dict[str, Any]] = []
    for adv_id, runtime_document in runtime_documents.items():
        for line in runtime_document.get("lines") or []:
            line_records.append(
                {
                    "advId": adv_id,
                    "order": line.get("order"),
                    "speakerId": line.get("speakerId"),
                    "text": line.get("text") or "",
                    "sceneIndex": line.get("sceneIndex"),
                    "spoiler": True,
                }
            )
    for adv_document in adv_documents.values():
        if adv_document.adv_id in runtime_documents:
            continue
        if adv_document.parse_status != "available":
            continue
        for line in adv_document.lines:
            line_records.append(
                {
                    "advId": adv_document.adv_id,
                    "order": line.get("order"),
                    "speakerId": line.get("speakerId"),
                    "text": line.get("text") or "",
                    "sceneIndex": line.get("sceneIndex"),
                    "spoiler": True,
                }
            )

    return {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "chapters": chapter_records,
        "entries": entry_records,
        "lines": line_records,
    }


def _build_quality_report(
    chapters: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    adv_documents: Mapping[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    counts_by_kind: dict[str, int] = {}
    for entry in entries:
        counts_by_kind[entry["kind"]] = counts_by_kind.get(entry["kind"], 0) + 1

    capability_states: dict[str, int] = {}
    for capability in capabilities:
        state = capability.get("state") or "missing"
        capability_states[state] = capability_states.get(state, 0) + 1

    adv_states: dict[str, int] = {}
    for document in adv_documents.values():
        state = document.parse_status
        adv_states[state] = adv_states.get(state, 0) + 1

    missing_scripts = sorted(
        {
            f"adv-{document.adv_master_id}"
            for document in adv_documents.values()
            if document.parse_status == "metadata_only"
        }
    )
    available_scripts = sorted(
        {
            document.adv_id
            for document in adv_documents.values()
            if document.parse_status == "available"
        }
    )

    return {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "chapterCount": len(chapters),
        "entryCount": len(entries),
        "entriesByKind": counts_by_kind,
        "capabilityCounts": capability_states,
        "advStateCounts": adv_states,
        "availableAdvIds": available_scripts,
        "missingScriptAdvIds": missing_scripts,
        "searchableLineCount": sum(
            len(document.lines) for document in adv_documents.values()
        ),
        "warnings": list(warnings),
    }


def build_story_pipeline(
    master_root: Path,
    master: MasterData,
    manifest_path: Path,
    extracted_root: Path,
    *,
    release_id: str,
    publication_policy: Mapping[str, Any] | None = None,
    adv_runtime_report: Mapping[str, Any] | None = None,
) -> StoryPipelineBuild:
    """Produce all four story artifacts in a single deterministic pass."""

    story_build = build_story_catalog(master_root, master)
    capability_build = build_media_capabilities(
        manifest_path,
        story_chapters=story_build.chapters,
        story_entries=story_build.entries,
        publication_policy=publication_policy,
    )
    adv_build = build_adv_database(
        manifest_path,
        extracted_root,
        story_build.entries,
    )

    runtime_documents = {
        document.adv_id: projected
        for document in adv_build.documents.values()
        if (
            projected := _experimental_runtime_document(
                adv_runtime_report,
                release_id=release_id,
                adv_master_id=document.adv_master_id,
            )
        )
    }

    capability_index = _capability_index(capability_build.capabilities)
    texts = _load_master_text(master_root)

    chapter_payloads: list[dict[str, Any]] = []
    for chapter in story_build.chapters:
        chapter_payloads.append(
            {
                **chapter,
                "capabilities": {
                    role: _public_capability(capability)
                    for role, capability in _chapter_capabilities(
                        chapter["id"], capability_index
                    ).items()
                },
            }
        )

    entry_payloads: list[dict[str, Any]] = []
    for entry in story_build.entries:
        adv = entry.get("adv") or {}
        adv_payload: dict[str, Any] | None = None
        if adv:
            adv_document = adv_build.documents.get(f"adv-{adv['masterId']}")
            runtime_audit = _adv_runtime_projection(
                adv_runtime_report,
                release_id=release_id,
                adv_master_id=int(adv["masterId"]),
            )
            runtime_document = runtime_documents.get(f"adv-{adv['masterId']}")
            adv_payload = {
                **adv,
                "shardStates": (
                    adv_document.shard_states if adv_document else {}
                ),
                "parseStatus": (
                    runtime_document.get("parseStatus")
                    if runtime_document
                    else adv_document.parse_status if adv_document else "metadata_only"
                ),
                "localeLines": (
                    adv_document.locale_lines if adv_document else []
                ),
                **({"runtimeAudit": runtime_audit} if runtime_audit else {}),
            }
        entry_payloads.append(
            {
                **entry,
                "adv": adv_payload,
                "title": (
                    _resolve_text(texts, adv.get("titleTextId")) if adv else ""
                ),
                "capabilities": {
                    role: _public_capability(capability)
                    for role, capability in _entry_capabilities(
                        entry["id"], capability_index
                    ).items()
                },
            }
        )

    database = {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "sourceReleaseId": release_id,
        "chapters": chapter_payloads,
        "entries": entry_payloads,
        "documents": {
            document.adv_id: {
                "advId": document.adv_id,
                "advMasterId": document.adv_master_id,
                "shardStates": document.shard_states,
                "parseStatus": (
                    runtime_documents.get(document.adv_id, {}).get("parseStatus")
                    or document.parse_status
                ),
                "localeLines": document.locale_lines,
                "scenes": runtime_documents.get(document.adv_id, {}).get(
                    "scenes", document.scenes
                ),
                "lines": runtime_documents.get(document.adv_id, {}).get(
                    "lines", document.lines
                ),
                "events": runtime_documents.get(document.adv_id, {}).get(
                    "events", []
                ),
                "unknownCommands": runtime_documents.get(document.adv_id, {}).get(
                    "unknownCommands", document.unknown_commands
                ),
                "limitations": runtime_documents.get(document.adv_id, {}).get(
                    "limitations", []
                ),
                **(
                    {"runtimeAudit": runtime_audit}
                    if (
                        runtime_audit := _adv_runtime_projection(
                            adv_runtime_report,
                            release_id=release_id,
                            adv_master_id=document.adv_master_id,
                        )
                    )
                    else {}
                ),
            }
            for document in adv_build.documents.values()
        },
    }

    media_capabilities = {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "sourceReleaseId": release_id,
        "capabilities": capability_build.capabilities,
        "byReference": capability_build.by_reference,
    }

    search_index = _build_search_index(
        story_build.chapters,
        story_build.entries,
        texts,
        adv_build.documents,
        runtime_documents,
    )
    quality_report = _build_quality_report(
        story_build.chapters,
        story_build.entries,
        capability_build.capabilities,
        adv_build.documents,
        [
            *story_build.warnings,
            *adv_build.warnings,
            *capability_build.warnings,
        ],
    )
    audit_sample = (
        adv_runtime_report.get("evidence", {}).get("sample", {})
        if isinstance(adv_runtime_report, Mapping)
        and isinstance(adv_runtime_report.get("evidence"), Mapping)
        else {}
    )
    audit_master_id = audit_sample.get("advMasterId")
    if isinstance(audit_master_id, int):
        audit_projection = _adv_runtime_projection(
            adv_runtime_report,
            release_id=release_id,
            adv_master_id=audit_master_id,
        )
        if audit_projection:
            quality_report["representativeAdvAudit"] = {
                "advMasterId": audit_master_id,
                **audit_projection,
            }

    return StoryPipelineBuild(
        database=database,
        search_index=search_index,
        quality_report=quality_report,
        media_capabilities=media_capabilities,
        warnings=[
            *story_build.warnings,
            *adv_build.warnings,
            *capability_build.warnings,
        ],
    )
