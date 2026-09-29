#!/usr/bin/env python3
"""Batch-extract images from Unity Addressables bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.catalog_adapter import (
    CatalogAdapter,
    catalog_snapshot_to_dict,
)


ANALYSIS_DIR = Path(__file__).resolve().parent
for dependency_dir in (ANALYSIS_DIR / "vendor", ANALYSIS_DIR / ".deps"):
    if dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))


def safe_name(value: str, limit: int = 80) -> str:
    value = re.sub(r"[\x00-\x1f/:*?\"<>|\\]+", "_", value).strip(" .")
    return (value or "unnamed")[:limit]


def bundle_key(path: Path, root: Path) -> str:
    relative = str(path.relative_to(root))
    digest = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:10]
    readable = safe_name(path.stem.rsplit("_", 1)[0], 60)
    return f"{readable}_{digest}"


def find_bundles(root: Path, recursive_unityfs: bool) -> list[Path]:
    if not recursive_unityfs:
        return sorted(root.glob("*.bundle"))

    bundles = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(8) == b"UnityFS\x00":
                bundles.append(path)
    return sorted(bundles)


def write_catalog_projection(catalog_path: Path, output_path: Path) -> dict[str, object]:
    """Write a normalized Catalog graph for extraction and pipeline tooling."""
    snapshot = CatalogAdapter().parse(catalog_path)
    projection = catalog_snapshot_to_dict(snapshot)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return projection


def build_cab_index(
    bundles: list[Path], unitypy: object
) -> tuple[dict[str, Path], list[dict[str, str]]]:
    cab_index: dict[str, Path] = {}
    failures: list[dict[str, str]] = []
    for index, bundle in enumerate(bundles, start=1):
        try:
            environment = unitypy.load(str(bundle))
            for cab_name in environment.cabs:
                cab_index.setdefault(cab_name.lower(), bundle)
        except Exception as exc:
            failures.append(
                {
                    "bundle": bundle.name,
                    "stage": "cab_index",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if index % 500 == 0 or index == len(bundles):
            print(
                f"indexed {index}/{len(bundles)} bundles; "
                f"{len(cab_index)} CAB entries",
                flush=True,
            )
    return cab_index, failures


def load_direct_dependencies(
    environment: object,
    bundle: Path,
    cab_index: dict[str, Path],
) -> list[str]:
    dependency_paths: dict[Path, str] = {}
    for asset in environment.assets:
        for external in asset.externals:
            cab_name = external.name.lower()
            dependency = cab_index.get(cab_name)
            if dependency is not None and dependency != bundle:
                dependency_paths.setdefault(dependency, cab_name)

    loaded = []
    for dependency, cab_name in dependency_paths.items():
        environment.load_file(str(dependency), is_dependency=True)
        loaded.append(cab_name)
    return loaded


def export_text_asset(data: object, output: Path) -> None:
    payload = getattr(data, "m_Script", getattr(data, "script", b""))
    if isinstance(payload, str):
        if has_surrogate_bytes(payload):
            output.write_bytes(payload.encode("utf-8", errors="surrogateescape"))
        else:
            output.write_text(payload, encoding="utf-8")
    else:
        output.write_bytes(bytes(payload))


def has_surrogate_bytes(value: str) -> bool:
    return any("\udc80" <= character <= "\udcff" for character in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--catalog",
        type=Path,
        help="optional Addressables binary/JSON Catalog to normalize alongside extraction",
    )
    parser.add_argument(
        "--recursive-unityfs",
        action="store_true",
        help="Recursively include extensionless files with a UnityFS header.",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Export only TextAsset objects.",
    )
    args = parser.parse_args()

    if args.catalog is not None:
        write_catalog_projection(args.catalog, args.output / "catalog.json")

    try:
        import UnityPy  # pylint: disable=import-outside-toplevel
    except ImportError as error:
        raise SystemExit(
            "UnityPy is required. Install analysis dependencies with:\n"
            "python3 -m pip install --target analysis/vendor "
            "-r analysis/requirements.txt"
        ) from error

    texture_dir = args.output / "textures"
    sprite_dir = args.output / "sprites"
    text_dir = args.output / "textassets"
    texture_dir.mkdir(parents=True, exist_ok=True)
    sprite_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    bundles = find_bundles(args.bundle_dir, args.recursive_unityfs)
    cab_index, index_failures = build_cab_index(bundles, UnityPy)
    type_counts: Counter[str] = Counter()
    exported: Counter[str] = Counter()
    dependency_loads: Counter[str] = Counter()
    records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = list(index_failures)
    skipped: list[dict[str, object]] = []

    for index, bundle in enumerate(bundles, start=1):
        try:
            env = UnityPy.load(str(bundle))
            loaded_dependencies = load_direct_dependencies(env, bundle, cab_index)
            for cab_name in loaded_dependencies:
                dependency_loads[cab_name] += 1
        except Exception as exc:
            failures.append(
                {
                    "bundle": bundle.name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        prefix = bundle_key(bundle, args.bundle_dir)
        for obj in env.objects:
            type_counts[obj.type.name] += 1
            export_types = (
                {"TextAsset"}
                if args.text_only
                else {"Texture2D", "Sprite", "TextAsset"}
            )
            if obj.type.name not in export_types:
                continue

            record: dict[str, object] = {
                "bundle": str(bundle.relative_to(args.bundle_dir)),
                "path_id": obj.path_id,
                "type": obj.type.name,
            }
            container_path = obj.container
            if container_path:
                record["container_path"] = container_path
            try:
                data = obj.read()
                name = str(getattr(data, "m_Name", "") or "")
                record["name"] = name
                filename_base = f"{prefix}_{obj.path_id}_{safe_name(name)}"
                if obj.type.name == "Texture2D":
                    width = int(getattr(data, "m_Width", 0))
                    height = int(getattr(data, "m_Height", 0))
                    record["width"] = width
                    record["height"] = height
                    if width <= 0 or height <= 0:
                        record["skipped_reason"] = "non-renderable zero-size texture"
                        skipped.append(record.copy())
                        records.append(record)
                        continue
                    output = texture_dir / f"{filename_base}.png"
                    data.image.save(output)
                elif obj.type.name == "Sprite":
                    output = sprite_dir / f"{filename_base}.png"
                    data.image.save(output)
                else:
                    payload = getattr(data, "m_Script", getattr(data, "script", b""))
                    if isinstance(payload, str) and not has_surrogate_bytes(payload):
                        stripped = payload.lstrip()
                        suffix = (
                            ".json"
                            if stripped.startswith(("{", "["))
                            else ".xml"
                            if stripped.startswith("<")
                            else ".txt"
                        )
                    else:
                        suffix = ".bin"
                    output = text_dir / f"{filename_base}{suffix}"
                    export_text_asset(data, output)
                record["exported_file"] = str(output.relative_to(args.output))
                exported[obj.type.name] += 1
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                failures.append(record.copy())
            records.append(record)

        if index % 100 == 0 or index == len(bundles):
            print(
                f"{index}/{len(bundles)} bundles; "
                f"{sum(exported.values())} assets; {len(failures)} failures",
                flush=True,
            )

    report = {
        "bundle_directory": str(args.bundle_dir),
        "bundle_count": len(bundles),
        "cab_index_count": len(cab_index),
        "dependency_loads": dict(dependency_loads),
        "type_counts": dict(type_counts),
        "exported": dict(exported),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "failure_count": len(failures),
        "failures": failures,
        "assets": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "bundle_count": len(bundles),
        "cab_index_count": len(cab_index),
        "dependency_cab_count": len(dependency_loads),
        "exported": dict(exported),
        "skipped_count": len(skipped),
        "failure_count": len(failures),
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
