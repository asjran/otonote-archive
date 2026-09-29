#!/usr/bin/env python3
"""Extract directly readable image assets and metadata from a Unity asset file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    value = re.sub(r"[\x00-\x1f/:*?\"<>|\\]+", "_", value).strip(" .")
    return value[:120] or "unnamed"


def json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent / ".deps"))
    import UnityPy  # pylint: disable=import-outside-toplevel

    args.output.mkdir(parents=True, exist_ok=True)
    texture_dir = args.output / "textures"
    sprite_dir = args.output / "sprites"
    texture_dir.mkdir(exist_ok=True)
    sprite_dir.mkdir(exist_ok=True)

    env = UnityPy.load(str(args.input))
    type_counts = Counter(obj.type.name for obj in env.objects)
    records: list[dict[str, Any]] = []
    scripts: list[dict[str, Any]] = []
    exported = Counter()
    failures: list[dict[str, Any]] = []

    for obj in env.objects:
        record: dict[str, Any] = {
            "path_id": obj.path_id,
            "type": obj.type.name,
        }
        try:
            data = obj.read()
            name = str(getattr(data, "m_Name", "") or "")
            if name:
                record["name"] = name

            if obj.type.name == "Texture2D":
                record["width"] = int(getattr(data, "m_Width", 0))
                record["height"] = int(getattr(data, "m_Height", 0))
                output = texture_dir / f"{obj.path_id}_{safe_name(name)}.png"
                data.image.save(output)
                record["exported_file"] = str(output.relative_to(args.output))
                exported["Texture2D"] += 1

            elif obj.type.name == "Sprite":
                output = sprite_dir / f"{obj.path_id}_{safe_name(name)}.png"
                data.image.save(output)
                record["exported_file"] = str(output.relative_to(args.output))
                exported["Sprite"] += 1

            elif obj.type.name == "MonoScript":
                script = {
                    "path_id": obj.path_id,
                    "name": name,
                    "class_name": str(getattr(data, "m_ClassName", "") or ""),
                    "namespace": str(getattr(data, "m_Namespace", "") or ""),
                    "assembly_name": str(getattr(data, "m_AssemblyName", "") or ""),
                }
                scripts.append(script)

            for key in ("m_IsReadable", "m_TextureFormat"):
                if hasattr(data, key):
                    record[key.removeprefix("m_").lower()] = json_value(
                        getattr(data, key)
                    )

        except Exception as exc:  # Keep a complete audit even if one object fails.
            failures.append(
                {
                    "path_id": obj.path_id,
                    "type": obj.type.name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        records.append(record)

    report = {
        "input": str(args.input),
        "unity_version": getattr(env, "unity_version", None),
        "object_count": len(env.objects),
        "type_counts": dict(type_counts),
        "exported": dict(exported),
        "failure_count": len(failures),
        "failures": failures,
        "objects": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "monoscripts.json").write_text(
        json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({key: report[key] for key in (
        "unity_version",
        "object_count",
        "type_counts",
        "exported",
        "failure_count",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
