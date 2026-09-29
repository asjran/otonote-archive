"""Build a shared media capability index for story and character-media modules.

Capability states (in evaluation order):

* ``available`` — required master references resolve, the resource file is
  present in the current release, and the publication policy allows it.
* ``metadata_only`` — Master relations resolve but the actual resource file
  is not in the current extraction.
* ``missing`` — a required reference exists but no resource is declared.
* ``unsupported`` — file exists but the adapter cannot interpret it.
* ``disabled`` — the public policy explicitly disables this capability.
* ``experimental`` — the adapter can use the resource, but the result has not
  yet passed the module's production acceptance gate.

The builder never inspects ``phone_dump`` paths from page code. The output
is the single source of truth for capability state across the site.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CAPABILITY_STATES = (
    "available",
    "metadata_only",
    "missing",
    "unsupported",
    "disabled",
    "experimental",
)


class MediaCapabilityError(ValueError):
    """Raised when media capability inputs are inconsistent."""


@dataclass(frozen=True)
class MediaCapabilityBuild:
    capabilities: list[dict[str, Any]]
    by_reference: dict[str, str]
    warnings: list[str]


def merge_media_capabilities(
    base_payload: Mapping[str, Any],
    additional: list[dict[str, Any]],
    *,
    release_id: str,
) -> dict[str, Any]:
    """Merge domain capabilities into the shared, single-writer payload."""

    base_release = base_payload.get("sourceReleaseId")
    if base_release not in {None, "", release_id}:
        raise MediaCapabilityError(
            "cannot merge capabilities from different releases: "
            f"{base_release!r} != {release_id!r}"
        )

    by_id: dict[str, dict[str, Any]] = {}
    for capability in [
        *(base_payload.get("capabilities") or []),
        *additional,
    ]:
        if not isinstance(capability, dict):
            raise MediaCapabilityError(
                "media capability must be an object"
            )
        capability_id = capability.get("id")
        if not isinstance(capability_id, str) or not capability_id:
            raise MediaCapabilityError(
                f"media capability has invalid id: {capability_id!r}"
            )
        state = capability.get("state")
        if state not in CAPABILITY_STATES:
            raise MediaCapabilityError(
                f"unsupported media capability state for {capability_id}: {state!r}"
            )
        existing = by_id.get(capability_id)
        if existing is not None and existing != capability:
            raise MediaCapabilityError(
                f"conflicting media capability id: {capability_id}"
            )
        by_id[capability_id] = dict(capability)

    return {
        "schemaVersion": int(base_payload.get("schemaVersion") or 1),
        "generatedAt": base_payload.get("generatedAt"),
        "sourceReleaseId": release_id,
        "capabilities": [by_id[key] for key in sorted(by_id)],
        "byReference": dict(base_payload.get("byReference") or {}),
    }


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise MediaCapabilityError(
            f"manifest not found: {manifest_path}"
        )
    return _load_json(manifest_path, {})


def _container_for(asset_name: str) -> str | None:
    if not asset_name:
        return None
    if asset_name.startswith("ui_banner_chapter_") and "episode" in asset_name:
        return f"Assets/AddressableResources/Story/Banner/Episode/{asset_name}.png"
    if asset_name.startswith("ui_banner_chapter_"):
        return f"Assets/AddressableResources/Story/Banner/Chapter/{asset_name}.png"
    if asset_name.startswith("ui_banner_storyfriend_"):
        return f"Assets/AddressableResources/Story/Banner/Episode/{asset_name}.png"
    if asset_name.startswith("ui_image_chapter_") and "episode" in asset_name:
        return f"Assets/AddressableResources/Story/Image/Episode/{asset_name}.png"
    if asset_name.startswith("ui_image_chapter_"):
        return f"Assets/AddressableResources/Story/Image/Chapter/{asset_name}.png"
    if asset_name.startswith("ui_icon_chapter_"):
        return f"Assets/AddressableResources/Story/Icon/{asset_name}.png"
    return None


def _stable_id(prefix: str, container: str, name: str) -> str:
    digest = hashlib.sha1(f"{container}:{name}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _index_manifest_records(
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    by_container: dict[str, dict[str, Any]] = {}
    for record in manifest.get("assets", []):
        if not isinstance(record, dict):
            continue
        container = str(record.get("container_path") or "")
        if not container:
            continue
        existing = by_container.get(container)
        if existing is None:
            by_container[container] = record
    return by_container


def _resolve_reference(
    asset_name: str,
    *,
    role: str,
    manifest_index: Mapping[str, dict[str, Any]],
    publication_policy: Mapping[str, Any],
) -> dict[str, Any]:
    container = _container_for(asset_name)
    record = manifest_index.get(container) if container else None

    placeholder = not asset_name or asset_name.upper() in {"", "TBD", "TODO"}

    if publication_policy.get("stories", {}).get("disabledRoles", {}).get(role):
        state = "disabled"
    elif placeholder:
        state = "metadata_only"
    elif record is None:
        state = "metadata_only"
    else:
        exported = record.get("exported_file")
        if not exported:
            state = "metadata_only"
        else:
            state = "available"

    capability_id = (
        _stable_id("media", container or role, asset_name or role)
        if container or asset_name
        else _stable_id("media", role, role)
    )

    return {
        "id": capability_id,
        "reference": asset_name or None,
        "role": role,
        "containerPath": container,
        "state": state,
        "previewUrl": None,
        "originalUrl": None,
        "sourceBundle": str(record.get("bundle") or "") if record else "",
        "sourcePathId": str(record.get("path_id") or "") if record else "",
        "exportedFile": str(record.get("exported_file") or "") if record else "",
    }


def build_media_capabilities(
    manifest_path: Path,
    *,
    story_chapters: list[dict[str, Any]],
    story_entries: list[dict[str, Any]],
    publication_policy: Mapping[str, Any] | None = None,
) -> MediaCapabilityBuild:
    """Compute per-reference capability state for story assets."""

    manifest = _load_manifest(manifest_path)
    manifest_index = _index_manifest_records(manifest)
    policy = publication_policy or {}
    warnings: list[str] = []

    capabilities: list[dict[str, Any]] = []
    by_reference: dict[str, str] = {}

    for chapter in story_chapters:
        for role, field in (
            ("chapter_banner", "bannerAssetName"),
            ("chapter_image", "imageAssetName"),
            ("chapter_icon", "iconAssetName"),
        ):
            asset_name = chapter.get(field) or ""
            capability = _resolve_reference(
                asset_name,
                role=role,
                manifest_index=manifest_index,
                publication_policy=policy,
            )
            capability["owner"] = {
                "kind": "chapter",
                "id": chapter["id"],
            }
            capabilities.append(capability)
            by_reference[f"chapter:{chapter['id']}:{role}"] = capability["id"]

    for entry in story_entries:
        if entry["kind"] == "main":
            entry_roles = (
                ("episode_banner", "bannerAssetName"),
                ("episode_image", "imageAssetName"),
            )
        elif entry["kind"] == "friendship":
            entry_roles = (("episode_banner", "bannerAssetName"),)
        else:
            entry_roles = ()

        for role, field in entry_roles:
            asset_name = entry.get(field) or ""
            capability = _resolve_reference(
                asset_name,
                role=role,
                manifest_index=manifest_index,
                publication_policy=policy,
            )
            capability["owner"] = {
                "kind": "entry",
                "id": entry["id"],
            }
            capabilities.append(capability)
            by_reference[f"entry:{entry['id']}:{role}"] = capability["id"]

        thumbnail = entry.get("thumbnailAssetName") or ""
        if (
            thumbnail
            and not entry.get("thumbnailIsPlaceholder", False)
            and entry["kind"] in {"main", "friendship"}
        ):
            capability = _resolve_reference(
                thumbnail,
                role=(
                    "friendship_banner"
                    if entry["kind"] == "friendship"
                    else "episode_banner"
                ),
                manifest_index=manifest_index,
                publication_policy=policy,
            )
            capability["owner"] = {
                "kind": "entry",
                "id": entry["id"],
            }
            capabilities.append(capability)
            by_reference[f"entry:{entry['id']}:thumbnail"] = capability["id"]

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for capability in capabilities:
        key = capability["id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(capability)

    return MediaCapabilityBuild(
        capabilities=deduped,
        by_reference=by_reference,
        warnings=warnings,
    )
