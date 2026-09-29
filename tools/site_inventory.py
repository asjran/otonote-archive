"""Measure logical bytes and physical unique files without counting aliases twice."""
import argparse
import json
import os
from pathlib import Path


def inventory(root: Path) -> dict:
    seen = set()
    groups = {}
    html = 0
    for directory, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            info = path.stat()
            identity = (info.st_dev, info.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            relative = path.relative_to(root)
            group = "/".join(relative.parts[:2]) if relative.parts[0] == "media" else relative.parts[0]
            summary = groups.setdefault(group, {"files": 0, "bytes": 0})
            summary["files"] += 1
            summary["bytes"] += info.st_size
            html += path.suffix == ".html"
    return {"root": str(root.resolve()), "files": len(seen), "htmlFiles": html,
            "bytes": sum(item["bytes"] for item in groups.values()), "groups": groups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory(args.root), indent=2) + "\n")
