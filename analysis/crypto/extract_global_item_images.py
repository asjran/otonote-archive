#!/usr/bin/env python3
"""Extract Master-referenced item art from the pinned Global phone capture."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.crypto.decrypt_global_formal_scores import (
    CATALOG_SHA256, KEY_FIELD_USAGE, METADATA_SHA256, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter


def extract(capture_root: Path, master_root: Path, metadata_path: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists")
    catalog = capture_root / "RemoteCatalog/catalog_main.bin"
    if sha256(catalog) != CATALOG_SHA256 or sha256(metadata_path) != METADATA_SHA256:
        raise ValueError("Global catalog or metadata digest mismatch")
    def rows(name):
        return json.loads((master_root / f"{name}.json").read_text())["_allData"]
    targets = {"item_assets_all_": {
        f"Assets/AddressableResources/{row['_imagePath']}.png"
        for row in rows("MasterItem") if row.get("_imagePath")
    }}
    for row in rows("MasterBandItem"):
        band, item = row["_bandId"], row["_id"]
        targets[f"band_assets_band_{band}_banditem_{item}_band_item_"] = {
            f"Assets/AddressableResources/Band/{band}/BandItem/{item}/band_item.png"
        }
    capture = json.loads((capture_root / "capture.json").read_text())
    recorded = {row["path"]: row for row in capture["files"]}
    locations = CatalogAdapter().parse(catalog).locations
    metadata = MetadataV39(metadata_path)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    assets, sources = [], []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as folder:
        temporary = Path(folder)
        for prefix, containers in targets.items():
            matches = [loc for loc in locations if loc.primary_key.startswith(prefix)
                       and re.fullmatch(r"[a-f0-9]{32}\.bundle", loc.primary_key[len(prefix):])
                       and loc.provider_id.endswith(".AssetBundleCryptProvider")]
            if len(matches) != 1:
                raise ValueError(f"expected unique catalog bundle: {prefix}")
            loc = matches[0]
            bundle_hash = loc.primary_key[:-7].rsplit("_", 1)[-1]
            cached = list((capture_root / "EncryptedBundles").glob(f"{bundle_hash}_*.bundle"))
            if len(cached) != 1:
                raise ValueError(f"expected unique cached bundle: {prefix}")
            source = cached[0]
            relative = source.relative_to(capture_root).as_posix()
            record = recorded.get(relative)
            if (not record or sha256(source) != record["sha256"]
                    or source.stat().st_size != record["size_bytes"]
                    or source.stat().st_size != loc.expected_size):
                raise ValueError(f"capture mismatch: {prefix}")
            env = UnityPy.load(decrypt_header(source.read_bytes(), loc.primary_key, key, seed))
            for container in sorted(containers):
                matches = [obj for path, obj in env.container.items()
                           if path == container and obj.type.name == "Texture2D"]
                if len(matches) != 1:
                    raise ValueError(f"expected unique texture: {container}")
                obj = matches[0]
                texture = obj.read()
                image = texture.image
                exported = "png/item-art-" + container.removeprefix("Assets/AddressableResources/").replace("/", "-")
                target = temporary / exported
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target, format="PNG")
                assets.append({"type": "Texture2D", "name": texture.m_Name,
                               "bundle": loc.primary_key, "path_id": obj.path_id,
                               "container_path": container, "exported_file": exported,
                               "width": image.width, "height": image.height, "sha256": sha256(target)})
            sources.append({"bundle": loc.primary_key, "source": relative,
                            "encryptedSha256": record["sha256"]})
        manifest = temporary / "manifest.json"
        manifest.write_text(json.dumps({"assets": assets}, ensure_ascii=False, indent=2) + "\n")
        report = {"schemaVersion": 1, "catalogSha256": CATALOG_SHA256,
                  "metadataSha256": METADATA_SHA256, "sourceBundleCount": len(sources),
                  "extractedImageCount": len(assets), "sources": sources,
                  "manifestSha256": sha256(manifest),
                  "masterSha256": {name: sha256(master_root / f"{name}.json")
                                   for name in ("MasterItem", "MasterBandItem")}}
        (temporary / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
        temporary.rename(output)
    return {key: report[key] for key in ("sourceBundleCount", "extractedImageCount", "manifestSha256")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.capture_root, args.master_root, args.metadata, args.output), indent=2))
