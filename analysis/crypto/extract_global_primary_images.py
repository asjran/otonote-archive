#!/usr/bin/env python3
"""Extract current Global character and card art from the verified phone cache."""

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


KINDS = (
    ("character", "character-image_assets_character-image-{id}everythinginitialdownload_", "Character/Image", ("character_thumbnail", "character_sprite")),
    ("member", "membercard_assets_membercard_{id}_member_full_", "MemberCard", ("member_full",)),
    ("support", "supportcard_assets_supportcard_{id}_snap_full_", "SupportCard", ("snap_full",)),
)


def rows(root: Path, name: str) -> list[dict]:
    return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))["_allData"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--avatars-only", action="store_true", help="Extract the 25 verified face icons")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists")
    catalog_path = args.capture_root / "RemoteCatalog/catalog_main.bin"
    if sha256(catalog_path) != CATALOG_SHA256 or sha256(args.metadata) != METADATA_SHA256:
        parser.error("captured catalog or IL2CPP metadata digest mismatch")
    capture = json.loads((args.capture_root / "capture.json").read_text(encoding="utf-8"))
    if (capture.get("package"), capture.get("version_name"), capture.get("version_code")) != ("com.bilibili.sirius", "1.0.1", 25):
        parser.error("wrong Global production package")
    recorded = {row["path"]: row for row in capture["files"]}
    locations = CatalogAdapter().parse(catalog_path).locations
    metadata = MetadataV39(args.metadata)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    identifiers = {
        "character": {int(row["_id"]) for row in rows(args.master_root, "MasterCharacter")},
        "member": {int(row["_assetID"]) for row in rows(args.master_root, "MasterMemberCard")},
        "support": {int(row["_assetID"]) for row in rows(args.master_root, "MasterSupportCard")},
    }
    if {kind: len(ids) for kind, ids in identifiers.items()} != {"character": 25, "member": 60, "support": 62}:
        parser.error("current Master identity set changed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{args.output.name}-", dir=args.output.parent) as temp_name:
        temp = Path(temp_name)
        assets = []
        sources = []
        kinds = (("character", KINDS[0][1], "Character/Image", ("character_face_icon",)),) if args.avatars_only else KINDS
        for kind, prefix, directory, names in kinds:
            for identifier in sorted(identifiers[kind]):
                exact_prefix = prefix.format(id=identifier)
                matches = [loc for loc in locations if loc.primary_key.startswith(exact_prefix)
                           and re.fullmatch(r"[a-f0-9]{32}\.bundle", loc.primary_key[len(exact_prefix):])
                           and loc.provider_id.endswith(".AssetBundleCryptProvider")]
                if len(matches) != 1:
                    raise ValueError(f"{kind} {identifier}: expected one catalog bundle")
                location = matches[0]
                bundle_id = location.primary_key[:-7].rsplit("_", 1)[-1]
                cache = list((args.capture_root / "EncryptedBundles").glob(f"{bundle_id}_*.bundle"))
                if len(cache) != 1:
                    raise ValueError(f"{kind} {identifier}: expected one cached bundle")
                source = cache[0]
                relative = source.relative_to(args.capture_root).as_posix()
                record = recorded.get(relative)
                if (not record or source.stat().st_size != record["size_bytes"]
                        or source.stat().st_size != location.expected_size
                        or sha256(source) != record["sha256"]):
                    raise ValueError(f"{kind} {identifier}: cached bundle digest mismatch")
                environment = UnityPy.load(decrypt_header(source.read_bytes(), location.primary_key, key, seed))
                for name in names:
                    container = f"Assets/AddressableResources/{directory}/{identifier}/{name}.png"
                    textures = [obj for path, obj in environment.container.items()
                                if path == container and obj.type.name == "Texture2D"]
                    if len(textures) != 1 or textures[0].read().m_Name != name:
                        raise ValueError(f"{kind} {identifier}: missing unique {name} Texture2D")
                    image = textures[0].read().image
                    if min(image.size) < 128:
                        raise ValueError(f"{kind} {identifier}: unexpected image size {image.size}")
                    exported = f"png/{kind}-{identifier}-{name}.png"
                    target = temp / exported
                    target.parent.mkdir(parents=True, exist_ok=True)
                    image.save(target, format="PNG")
                    assets.append({
                        "type": "Texture2D", "name": name, "bundle": location.primary_key,
                        "path_id": textures[0].path_id, "container_path": container,
                        "exported_file": exported, "width": image.width, "height": image.height,
                        "sha256": sha256(target),
                    })
                sources.append({"kind": kind, "id": identifier, "bundle": location.primary_key,
                                "source": relative, "encryptedSha256": record["sha256"]})
        if len(assets) != (25 if args.avatars_only else 172):
            raise ValueError(f"unexpected primary image count: {len(assets)}")
        (temp / "manifest.json").write_text(json.dumps({"assets": assets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = {"schemaVersion": 1, "catalogSha256": CATALOG_SHA256,
                  "metadataSha256": METADATA_SHA256, "sourceBundleCount": len(sources),
                  "extractedImageCount": len(assets), "sources": sources,
                  "manifestSha256": sha256(temp / "manifest.json")}
        (temp / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.rename(args.output)
    print(json.dumps({key: report[key] for key in ("sourceBundleCount", "extractedImageCount", "manifestSha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
