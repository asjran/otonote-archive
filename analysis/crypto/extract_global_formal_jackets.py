#!/usr/bin/env python3
"""Extract verified formal Global music jackets from the captured phone bundles."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from analysis.crypto.decrypt_global_formal_scores import (
    CATALOG_SHA256,
    KEY_FIELD_USAGE,
    METADATA_SHA256,
    NONCE_SEED_FIELD_USAGE,
    MetadataV39,
    UnityPy,
    decrypt_header,
    field_bytes,
    sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter

JACKET = re.compile(r"^image_assets_image_jacket_(jkt_\d{3}_\d{6})_[0-9a-f]{32}\.bundle$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new isolated directory")
    if sha256(args.metadata) != METADATA_SHA256:
        parser.error("metadata digest differs from the verified Global production build")
    catalog_path = args.capture_root / "RemoteCatalog/catalog_main.bin"
    if sha256(catalog_path) != CATALOG_SHA256:
        parser.error("catalog digest differs from the verified device capture")
    capture = json.loads((args.capture_root / "capture.json").read_text(encoding="utf-8"))
    if (capture.get("package"), capture.get("version_name"), capture.get("version_code")) != (
        "com.bilibili.sirius", "1.0.1", 25
    ):
        parser.error("device capture has the wrong package identity")
    recorded = {row["path"]: row for row in capture["files"]}
    master = json.loads((args.master_root / "MasterLiveMusic.json").read_text(encoding="utf-8"))
    names = {str(row["_jacketAssetName"]) for row in master["_allData"]}
    if len(master["_allData"]) != 84 or len(names) != 84 or any(not re.fullmatch(r"jkt_\d{3}_\d{6}", name) for name in names):
        parser.error("formal Master must name 84 distinct jackets")
    catalog = CatalogAdapter().parse(catalog_path)
    locations = {}
    for location in catalog.locations:
        if not location.provider_id.endswith(".AssetBundleCryptProvider"):
            continue
        match = JACKET.fullmatch(location.primary_key)
        if match and match.group(1) in names:
            locations.setdefault(match.group(1), []).append(location)
    if set(locations) != names or any(len(items) != 1 for items in locations.values()):
        parser.error("formal jacket names do not map one-to-one to the captured catalog")
    metadata = MetadataV39(args.metadata)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{args.output.name}-", dir=args.output.parent) as temporary_name:
        temporary = Path(temporary_name)
        results = []
        for name in sorted(names):
            location = locations[name][0]
            identifier = location.primary_key[:-7].rsplit("_", 1)[-1]
            candidates = list((args.capture_root / "EncryptedBundles").glob(f"{identifier}_*.bundle"))
            if len(candidates) != 1:
                raise ValueError(f"{name}: expected one cached bundle, got {len(candidates)}")
            source = candidates[0]
            relative = source.relative_to(args.capture_root).as_posix()
            row = recorded.get(relative)
            if not row or source.stat().st_size != row["size_bytes"] or sha256(source) != row["sha256"]:
                raise ValueError(f"{name}: device capture digest mismatch")
            if source.stat().st_size != location.expected_size:
                raise ValueError(f"{name}: catalog size mismatch")
            clear = decrypt_header(source.read_bytes(), location.primary_key, key, seed)
            environment = UnityPy.load(clear)
            sprites = [obj.read() for obj in environment.objects if obj.type.name == "Sprite"]
            textures = [obj.read() for obj in environment.objects if obj.type.name == "Texture2D"]
            if len(sprites) != 1 or len(textures) != 1 or textures[0].m_Name != name:
                raise ValueError(f"{name}: missing unique named Sprite and Texture2D")
            image = sprites[0].image
            if image.width < 256 or image.height < 256:
                raise ValueError(f"{name}: unexpected Sprite dimensions {image.size}")
            target = temporary / "png" / f"{name}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")
            results.append({
                "name": name, "source": relative, "catalogBundle": location.primary_key,
                "spriteName": sprites[0].m_Name,
                "encryptedSha256": row["sha256"], "pngSha256": sha256(target),
                "width": image.width, "height": image.height,
            })
        report = {
            "schemaVersion": 1, "package": capture["package"], "version": "1.0.1 (25)",
            "catalogSha256": CATALOG_SHA256, "metadataSha256": METADATA_SHA256,
            "masterJackets": len(names), "extractedJackets": len(results), "results": results,
        }
        (temporary / "validation.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        temporary.rename(args.output)
    print(json.dumps({k: report[k] for k in ("masterJackets", "extractedJackets")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
