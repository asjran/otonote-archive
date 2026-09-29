"""Normalize AnonTokyo Studio map data behind one small interface."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


class AnonTokyoStudioError(RuntimeError):
    """Raised when Studio input cannot produce a trustworthy map document."""


def _number_pair(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise AnonTokyoStudioError(f"{label} must be an object")
    try:
        return {"x": float(value["x"]), "y": float(value["y"])}
    except (KeyError, TypeError, ValueError) as exc:
        raise AnonTokyoStudioError(f"{label} must contain numeric x and y") from exc


def _int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise AnonTokyoStudioError(f"{label} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AnonTokyoStudioError(f"{label} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise AnonTokyoStudioError(f"{label} must be at least {minimum}")
    return result


def _objects(rows: Any, *, fixed: bool) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise AnonTokyoStudioError("map object collection must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise AnonTokyoStudioError("map object must be an object")
        instance_id = str(row.get("_id", ""))
        if not instance_id or instance_id in seen:
            raise AnonTokyoStudioError("map object ids must be non-empty and unique")
        seen.add(instance_id)
        config_key = "_configId" if fixed else "_configID"
        config_id = str(row.get(config_key, ""))
        if not config_id:
            raise AnonTokyoStudioError("map object config id is missing")
        result.append(
            {
                "instanceId": instance_id,
                "configId": config_id,
                "tileIndex": _int(
                    row.get("_tileIndex") if fixed else row.get("_tIdx"),
                    "map object tile index",
                    minimum=0,
                ),
                "direction": _int(row.get("_forward", 0), "map object direction", minimum=0),
            }
        )
    return result


def _static_scene_image_key(address: Any) -> str | None:
    if not isinstance(address, str) or not address.strip():
        return None
    leaf = address.rstrip("/").rsplit("/", 1)[-1]
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", leaf)
    if not match:
        return None
    kind, number = match.groups()
    normalized = {
        "Plant": "Plants",
    }.get(kind, kind)
    if normalized not in {
        "Building",
        "Deco",
        "Facility",
        "Installation",
        "Plants",
        "Stand",
        "Tile",
        "Vender",
    }:
        return None
    return f"AT_Map_Outdoor_{normalized} ({int(number)})"


def _static_definitions(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        config_id = str(row.get("_id", ""))
        size = row.get("_size")
        directions = row.get("_direction")
        if (
            not config_id
            or not isinstance(size, list)
            or len(size) != 2
            or not all(isinstance(value, int) and value > 0 for value in size)
            or not isinstance(directions, list)
        ):
            continue
        normalized_directions = sorted(
            {
                value
                for value in directions
                if isinstance(value, int) and 0 <= value <= 3
            }
        )
        if not normalized_directions:
            continue
        result[config_id] = {
            "configId": config_id,
            "footprint": {"width": size[0], "height": size[1]},
            "directions": normalized_directions,
            "imageKey": _static_scene_image_key(row.get("_address")),
        }
    return result


def build_studio_map_document(
    map_config_path: Path,
    *,
    static_decoration_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Read and validate one MapConfig file for the internal projection."""
    try:
        raw_bytes = map_config_path.read_bytes()
        value = json.loads(raw_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise AnonTokyoStudioError("map config is unreadable") from exc
    if not isinstance(value, Mapping):
        raise AnonTokyoStudioError("map config root must be an object")

    width = _int(value.get("countX"), "map width", minimum=1)
    height = _int(value.get("countY"), "map height", minimum=1)
    tiles = value.get("tiles")
    if not isinstance(tiles, list) or len(tiles) != width * height:
        raise AnonTokyoStudioError("map tile count does not match grid dimensions")

    indexes: set[int] = set()
    editable: list[int] = []
    walkable: list[int] = []
    for tile in tiles:
        if not isinstance(tile, Mapping):
            raise AnonTokyoStudioError("map tile must be an object")
        index = _int(tile.get("idx"), "tile index", minimum=0)
        if index in indexes:
            raise AnonTokyoStudioError("map tile indexes must be unique")
        indexes.add(index)
        if _int(tile.get("editable", 0), "tile editable flag") == 1:
            editable.append(index)
        if _int(tile.get("walkable", 0), "tile walkable flag") == 1:
            walkable.append(index)
    if indexes != set(range(width * height)):
        raise AnonTokyoStudioError("map tile indexes must be contiguous")

    initial_objects = _objects(value.get("editableObjects", []), fixed=False)
    fixed_objects = _objects(value.get("staticObjects", []), fixed=True)
    for item in (*initial_objects, *fixed_objects):
        if item["tileIndex"] not in indexes:
            raise AnonTokyoStudioError("map object references an unknown tile")

    definitions = _static_definitions(static_decoration_rows)
    used_definitions = [
        definitions[config_id]
        for config_id in sorted({item["configId"] for item in fixed_objects})
        if config_id in definitions
    ]

    return {
        "schemaVersion": 1,
        "sourceHash": hashlib.sha256(raw_bytes).hexdigest(),
        "mediaKeys": sorted(
            {
                item["imageKey"]
                for item in used_definitions
                if isinstance(item.get("imageKey"), str)
            }
        ),
        "map": {
            "index": _int(value.get("mapIndex"), "map index", minimum=0),
            "grid": {"width": width, "height": height},
            "geometry": {
                "startPosition": _number_pair(value.get("startPosition"), "start position"),
                "tileSize": _number_pair(value.get("tileSize"), "tile size"),
                "horizontalDirection": _number_pair(value.get("mapHDir"), "horizontal direction"),
                "verticalDirection": _number_pair(value.get("mapVDir"), "vertical direction"),
            },
            "initialStoreSize": {
                "width": _int(value.get("storeSizeX"), "store width", minimum=1),
                "height": _int(value.get("storeSizeY"), "store height", minimum=1),
            },
            "marketTileIndex": _int(value.get("marketLeftTop"), "market tile index", minimum=0),
            "warehouse": {
                "configId": str(value.get("warehouseConfigId", "")),
                "tileIndex": _int(value.get("warehouseTileIndex"), "warehouse tile index", minimum=0),
            },
            "deliveryStartTileIndex": _int(value.get("deliveryStartTile"), "delivery tile index", minimum=0),
            "editableTileIndexes": sorted(editable),
            "walkableTileIndexes": sorted(walkable),
            "initialObjects": initial_objects,
            "fixedObjects": fixed_objects,
            "staticDefinitions": used_definitions,
        },
    }
