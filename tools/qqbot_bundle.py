"""Build a portable read-only QQ bot content bundle from a formal site artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from backend.qqbot.content import Content, ContentError, DATA_FILES, inside, validate_identity


def build(site_root: Path, output: Path) -> dict:
    if output.exists():
        raise ContentError("output must not exist; use a new versioned bundle directory")
    data = site_root / "global/zh-CN/data"
    catalog = json.loads((data / "catalog.json").read_text())
    systems = json.loads((data / "global-systems.json").read_text())
    release_id = catalog["release"]["id"]
    validate_identity(catalog, systems, release_id)
    match = re.match(r"global-prod-(\d{4})(\d{2})(\d{2})-", release_id)
    if not match:
        raise ContentError("source release does not have a verified snapshot date")
    manifest = {"schemaVersion": 1, "releaseId": release_id,
                "snapshotDate": "-".join(match.groups()), "files": {}, "images": {}}
    output.mkdir(parents=True)
    (output / "images").mkdir()
    try:
        for name in DATA_FILES:
            shutil.copyfile(data / name, output / name)
        for asset in catalog["assets"]:
            if asset.get("publicPolicy") != "public" or asset.get("sourceReleaseId") != release_id:
                continue
            preview = asset.get("previewUrl")
            if not preview or not re.fullmatch(r"asset-[a-z0-9-]+", asset["id"]):
                continue
            source = inside(site_root, preview.lstrip("/"))
            if not source.is_file():
                continue
            relative = f"images/{asset['id']}{source.suffix}"
            shutil.copyfile(source, output / relative)
            manifest["images"][asset["id"]] = relative
        for file in sorted(output.rglob("*")):
            if file.is_file():
                manifest["files"][file.relative_to(output).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        Content(output)
    except Exception:
        # Keep incomplete candidate for diagnosis; it is never activated automatically.
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.site_root.resolve(), args.output.resolve())
    print(json.dumps({"releaseId": result["releaseId"], "images": len(result["images"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
