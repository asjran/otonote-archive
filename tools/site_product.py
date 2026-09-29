"""V1 publication policy. Source assets are never modified by this module."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/site-product.json"


def policy() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def closed_data(name: str) -> bool:
    if name in {"story-library.json", "story-text"}:
        return False
    return name.startswith(tuple(policy()["closedDataPrefixes"]))


def prepare_public_data(root: Path) -> None:
    """Prune only isolated build workspaces, never the source public tree."""
    import shutil

    for path in list(root.iterdir()):
        if closed_data(path.name):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    search = root / "unified-search-index.json"
    if search.is_file():
        payload = json.loads(search.read_text())
        payload["entries"] = [entry for entry in payload.get("entries", []) if entry.get("type") != "story"]
        # Replace rather than overwrite: build inputs may be hard-linked.
        search.unlink()
        search.write_text(json.dumps(payload, ensure_ascii=False))
    index = root / "media-index.json"
    if index.is_file():
        import hashlib
        payload = json.loads(index.read_text())
        allowed = tuple(f"/media/{name}/" for name in policy()["mediaDirectories"])

        def supported(value):
            if isinstance(value, str):
                return not value.startswith("/media/") or value.startswith(allowed)
            if isinstance(value, dict):
                return all(supported(v) for v in value.values())
            if isinstance(value, list):
                return all(supported(v) for v in value)
            return True

        payload["records"] = [r for r in payload.get("records", []) if supported(r)]
        payload["recordCount"] = len(payload["records"])
        payload["bySourceUrl"] = {key: value for key, value in payload.get("bySourceUrl", {}).items() if supported(key) and supported(value)}
        payload["sha256"] = hashlib.sha256(json.dumps(payload["records"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        index.unlink()
        index.write_text(json.dumps(payload, ensure_ascii=False))


def copy_media(source: Path, destination: Path) -> None:
    import shutil

    destination.mkdir()
    for name in policy()["mediaDirectories"]:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, destination / name)
