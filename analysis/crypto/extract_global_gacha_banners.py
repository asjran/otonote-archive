#!/usr/bin/env python3
"""Verify and extract the nine Global production gacha banner textures."""

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

from analysis.crypto.decrypt_global_formal_scores import (  # noqa: E402
    CATALOG_SHA256, KEY_FIELD_USAGE, METADATA_SHA256, NONCE_SEED_FIELD_USAGE,
    MetadataV39, UnityPy, decrypt_header, field_bytes, sha256,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter  # noqa: E402


def extract(capture_root: Path, master_root: Path, metadata_path: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists")
    catalog_path = capture_root / "RemoteCatalog/catalog_main.bin"
    if sha256(catalog_path) != CATALOG_SHA256 or sha256(metadata_path) != METADATA_SHA256:
        raise ValueError("Global production catalog or metadata digest mismatch")
    capture = json.loads((capture_root / "capture.json").read_text(encoding="utf-8"))
    recorded = {row["path"]: row for row in capture["files"]}
    gacha_rows = json.loads((master_root / "MasterGacha.json").read_text(encoding="utf-8"))["_allData"]
    banner_names = {row["_bannerAssetName"].split("/")[-1] for row in gacha_rows}
    if len(banner_names) != 9:
        raise ValueError("expected nine distinct MasterGacha banner names")
    locations = CatalogAdapter().parse(catalog_path).locations
    metadata = MetadataV39(metadata_path)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temp_name:
        temporary = Path(temp_name)
        assets = []
        sources = []
        for name in sorted(banner_names):
            prefix = f"gacha_assets_gacha_banner_{name}_"
            matches = [loc for loc in locations if loc.primary_key.startswith(prefix)
                       and re.fullmatch(r"[a-f0-9]{32}\.bundle", loc.primary_key[len(prefix):])
                       and loc.provider_id.endswith(".AssetBundleCryptProvider")]
            if len(matches) != 1:
                raise ValueError(f"{name}: expected one catalog bundle")
            location = matches[0]
            bundle_id = location.primary_key[:-7].rsplit("_", 1)[-1]
            cached = list((capture_root / "EncryptedBundles").glob(f"{bundle_id}_*.bundle"))
            if len(cached) != 1:
                raise ValueError(f"{name}: expected one cached bundle")
            source = cached[0]
            relative = source.relative_to(capture_root).as_posix()
            record = recorded.get(relative)
            if (not record or source.stat().st_size != record["size_bytes"]
                    or source.stat().st_size != location.expected_size
                    or sha256(source) != record["sha256"]):
                raise ValueError(f"{name}: cached bundle digest mismatch")
            environment = UnityPy.load(decrypt_header(source.read_bytes(), location.primary_key, key, seed))
            container = f"Assets/AddressableResources/Gacha/Banner/{name}.png"
            textures = [obj for path, obj in environment.container.items()
                        if path == container and obj.type.name == "Texture2D"]
            if len(textures) != 1 or textures[0].read().m_Name != name:
                raise ValueError(f"{name}: missing unique Texture2D")
            image = textures[0].read().image
            if min(image.size) < 128:
                raise ValueError(f"{name}: unexpected texture size")
            exported = f"png/{name}.png"
            target = temporary / exported
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")
            assets.append({
                "type": "Texture2D", "name": name, "bundle": location.primary_key,
                "path_id": textures[0].path_id, "container_path": container,
                "exported_file": exported, "width": image.width, "height": image.height,
                "sha256": sha256(target),
            })
            sources.append({"name": name, "source": relative, "encryptedSha256": record["sha256"]})
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(json.dumps({"assets": assets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = {"schemaVersion": 1, "catalogSha256": CATALOG_SHA256,
                  "metadataSha256": METADATA_SHA256, "sourceBundleCount": len(sources),
                  "extractedImageCount": len(assets), "sources": sources,
                  "manifestSha256": sha256(manifest_path)}
        (temporary / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.rename(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.capture_root, args.master_root, args.metadata, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
