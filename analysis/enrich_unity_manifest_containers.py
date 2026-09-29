#!/usr/bin/env python3
"""Add Unity AssetBundle container paths to an existing extraction manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
        raise ValueError("manifest must be an object with an assets array")
    return value


def bundle_record_keys(
    manifest: dict[str, Any],
) -> dict[str, set[tuple[int, str]]]:
    keys: dict[str, set[tuple[int, str]]] = {}
    for record in manifest["assets"]:
        if not isinstance(record, dict):
            continue
        bundle = record.get("bundle")
        path_id = record.get("path_id")
        object_type = record.get("type")
        if not isinstance(bundle, str) or not isinstance(path_id, int):
            continue
        if not isinstance(object_type, str):
            continue
        keys.setdefault(bundle, set()).add((path_id, object_type))
    return keys


def scan_container_paths(
    bundle_root: Path,
    wanted: dict[str, set[tuple[int, str]]],
) -> tuple[dict[tuple[str, int, str], str], list[str]]:
    dependency_dir = Path(__file__).resolve().parent / ".deps"
    sys.path.insert(0, str(dependency_dir))
    import UnityPy  # pylint: disable=import-outside-toplevel

    containers: dict[tuple[str, int, str], str] = {}
    failures: list[str] = []
    for bundle_name, keys in sorted(wanted.items()):
        bundle_path = bundle_root / bundle_name
        if not bundle_path.is_file():
            failures.append(f"missing bundle: {bundle_name}")
            continue
        try:
            environment = UnityPy.load(str(bundle_path))
            for obj in environment.objects:
                object_key = (obj.path_id, obj.type.name)
                if object_key not in keys:
                    continue
                container_path = obj.container
                if not container_path:
                    continue
                key = (bundle_name, obj.path_id, obj.type.name)
                previous = containers.get(key)
                if previous and previous != container_path:
                    failures.append(
                        f"conflicting container for {bundle_name}:{obj.path_id}"
                    )
                    continue
                containers[key] = container_path
        except Exception as exc:  # Keep a complete report for partial caches.
            failures.append(
                f"failed bundle {bundle_name}: {type(exc).__name__}: {exc}"
            )
    return containers, failures


def enrich_manifest(
    manifest: dict[str, Any],
    containers: dict[tuple[str, int, str], str],
) -> dict[str, int]:
    matched = 0
    already_present = 0
    missing = 0
    for record in manifest["assets"]:
        if not isinstance(record, dict):
            continue
        current = record.get("container_path")
        if isinstance(current, str) and current:
            already_present += 1
            continue
        key = (
            str(record.get("bundle", "")),
            int(record.get("path_id", 0)),
            str(record.get("type", "")),
        )
        container_path = containers.get(key)
        if container_path:
            record["container_path"] = container_path
            matched += 1
        else:
            missing += 1
    return {
        "matched": matched,
        "already_present": already_present,
        "missing": missing,
    }


def write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without modifying the manifest.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    wanted = bundle_record_keys(manifest)
    containers, failures = scan_container_paths(args.bundle_root, wanted)
    counts = enrich_manifest(manifest, containers)
    report = {
        "bundles": len(wanted),
        "container_paths": len(containers),
        **counts,
        "failure_count": len(failures),
        "failures": failures,
    }
    if not args.dry_run:
        write_json_atomic(args.manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
