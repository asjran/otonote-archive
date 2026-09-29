"""Register the verified Global 1.0.1 phone snapshot as isolated release inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.crypto.decrypt_global_formal_scores import (
    KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE, MetadataV39, UnityPy,
    decrypt_header, field_bytes,
)
from tools.build_global_formal_master_candidate import verify_device_inputs
from tools.resource_pipeline.golden import CURRENT_SITE_MASTER_TABLES, _master_aggregate, _master_row_count
from tools.release_preflight import digest
from tools.score_inputs import write_score_inputs


RELEASE_ID = "global-prod-20260924-v1-0-1-25-39b5d81f"
CAPTURE = ROOT / "input/global/device-files/2026-09-24-v1.0.1-25"
APK_CAPTURE = ROOT / "input/global/apks/2026-09-22-v1.0.1-25"
MASTER = ROOT / "input/global/decrypted/2026-09-24-v1.0.1-25/master-json"
METADATA = ROOT / "input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat"
JACKETS = ROOT / "output/verification/global-jackets-20260924-v1"
PRIMARY_IMAGES = ROOT / "output/verification/global-primary-images-20260924-v1"
GACHA_BANNERS = ROOT / "output/verification/global-gacha-banners-20260924-v1"
SCORES = ROOT / "output/verification/global-score-json-20260924-v3"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def register(output: Path, *, ui_icons: Path | None = None, item_images: Path | None = None, avatars: Path | None = None) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("formal output already exists")
    provenance = verify_device_inputs(APK_CAPTURE, CAPTURE, MASTER)
    jacket_report = read_json(JACKETS / "validation.json")
    primary_report = read_json(PRIMARY_IMAGES / "validation.json")
    banner_report = read_json(GACHA_BANNERS / "validation.json")
    score_report = read_json(SCORES / "validation.json")
    if (jacket_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
            or score_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
            or jacket_report.get("extractedJackets") != 84
            or score_report.get("expectedRegularScores") != 336
            or score_report.get("failedBundles") != 0):
        raise ValueError("verified jacket/score report differs from the captured catalog")
    if (primary_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
            or primary_report.get("metadataSha256") != digest(METADATA)
            or primary_report.get("sourceBundleCount") != 147
            or primary_report.get("extractedImageCount") != 172
            or digest(PRIMARY_IMAGES / "manifest.json") != primary_report.get("manifestSha256")):
        raise ValueError("verified primary images differ from the captured catalog")
    if (banner_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
            or banner_report.get("metadataSha256") != digest(METADATA)
            or banner_report.get("sourceBundleCount") != 9
            or banner_report.get("extractedImageCount") != 9
            or digest(GACHA_BANNERS / "manifest.json") != banner_report.get("manifestSha256")):
        raise ValueError("verified gacha banners differ from the captured catalog")
    if digest(METADATA) != jacket_report["metadataSha256"] or digest(METADATA) != score_report["metadataSha256"]:
        raise ValueError("IL2CPP metadata digest mismatch")
    if ui_icons is not None:
        ui_report = read_json(ui_icons / "validation.json")
        if (ui_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
                or ui_report.get("metadataSha256") != digest(METADATA)
                or ui_report.get("apkSha256") != digest(APK_CAPTURE / "base.apk")
                or ui_report.get("extractedImageCount") != 51
                or ui_report.get("manifestSha256") != digest(ui_icons / "manifest.json")):
            raise ValueError("verified UI icons differ from the captured package")
    item_count = 0
    if item_images is not None:
        item_report = read_json(item_images / "validation.json")
        item_assets = read_json(item_images / "manifest.json")["assets"]
        expected_containers = {
            f"Assets/AddressableResources/{row['_imagePath']}.png"
            for row in read_json(MASTER / "MasterItem.json")["_allData"] if row.get("_imagePath")
        } | {
            f"Assets/AddressableResources/Band/{row['_bandId']}/BandItem/{row['_id']}/band_item.png"
            for row in read_json(MASTER / "MasterBandItem.json")["_allData"]
        }
        if (item_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
                or item_report.get("metadataSha256") != digest(METADATA)
                or item_report.get("manifestSha256") != digest(item_images / "manifest.json")
                or item_report.get("masterSha256") != {
                    name: digest(MASTER / f"{name}.json") for name in ("MasterItem", "MasterBandItem")}
                or {row["container_path"] for row in item_assets} != expected_containers
                or len(item_assets) != len(expected_containers)):
            raise ValueError("verified item images differ from the captured package")
        captured = {row["path"]: row for row in read_json(CAPTURE / "capture.json")["files"]}
        for source in item_report["sources"]:
            record = captured.get(source["source"])
            if (not record or record["sha256"] != source["encryptedSha256"]
                    or digest(CAPTURE / source["source"]) != source["encryptedSha256"]):
                raise ValueError("item image source differs from captured bundle")
        item_count = len(item_assets)
    if avatars is not None:
        avatar_report = read_json(avatars / "validation.json")
        if (avatar_report.get("catalogSha256") != provenance["remoteCatalogSha256"]
                or avatar_report.get("metadataSha256") != digest(METADATA)
                or avatar_report.get("sourceBundleCount") != 25
                or avatar_report.get("extractedImageCount") != 25
                or avatar_report.get("manifestSha256") != digest(avatars / "manifest.json")):
            raise ValueError("verified avatars differ from the captured package")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary_name:
        temporary = Path(temporary_name)
        master_target = temporary / "master"
        master_target.mkdir()
        table_records = []
        rows = {}
        for source in sorted(MASTER.glob("Master*.json")):
            target = master_target / source.name
            shutil.copyfile(source, target)
            if digest(target) != digest(source):
                raise ValueError(f"Master copy changed: {source.name}")
            table_records.append({"logicalName": source.name, "sha256": digest(target)})
            if source.stem in CURRENT_SITE_MASTER_TABLES:
                rows[source.stem] = _master_row_count(read_json(target), source.stem)
        if len(table_records) != 240 or set(rows) != set(CURRENT_SITE_MASTER_TABLES):
            raise ValueError("formal Master table set is incomplete")

        metadata = MetadataV39(METADATA)
        key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
        seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
        capture_records = {row["path"]: row for row in read_json(CAPTURE / "capture.json")["files"]}
        assets = []
        for row in sorted(jacket_report["results"], key=lambda item: item["name"]):
            source = CAPTURE / row["source"]
            recorded = capture_records.get(row["source"])
            if not recorded or digest(source) != row["encryptedSha256"] or recorded["sha256"] != row["encryptedSha256"]:
                raise ValueError(f"jacket bundle changed: {row['name']}")
            image = JACKETS / "png" / f"{row['name']}.png"
            if digest(image) != row["pngSha256"]:
                raise ValueError(f"jacket image changed: {row['name']}")
            environment = UnityPy.load(decrypt_header(source.read_bytes(), row["catalogBundle"], key, seed))
            container = f"Assets/AddressableResources/Image/Jacket/{row['name']}.png"
            textures = [obj for path, obj in environment.container.items() if path == container and obj.type.name == "Texture2D"]
            if len(textures) != 1 or textures[0].read().m_Name != row["name"]:
                raise ValueError(f"jacket Texture2D identity changed: {row['name']}")
            target = temporary / "assets/png" / image.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image, target)
            assets.append({
                "type": "Texture2D", "name": row["name"], "bundle": row["catalogBundle"],
                "path_id": textures[0].path_id, "container_path": container,
                "exported_file": f"png/{image.name}", "width": row["width"], "height": row["height"],
                "sha256": row["pngSha256"],
            })
        if len(assets) != 84 or len({row["name"] for row in assets}) != 84:
            raise ValueError("formal jacket set is incomplete")
        for image_root in (PRIMARY_IMAGES, GACHA_BANNERS, *((ui_icons,) if ui_icons else ()),
                           *((item_images,) if item_images else ()), *((avatars,) if avatars else ())):
            for row in read_json(image_root / "manifest.json")["assets"]:
                if not isinstance(row, dict) or not isinstance(row.get("exported_file"), str):
                    raise ValueError("invalid image manifest record")
                relative = Path(row["exported_file"])
                if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "png":
                    raise ValueError("unsafe image path")
                source = image_root / relative
                if digest(source) != row.get("sha256"):
                    raise ValueError(f"image digest mismatch: {relative}")
                target = temporary / "assets" / relative
                if target.exists():
                    raise ValueError(f"duplicate image path: {relative}")
                shutil.copyfile(source, target)
                assets.append(row)
        expected_count = (316 if ui_icons else 265) + item_count + (25 if avatars else 0)
        identities = {(row["bundle"], row["path_id"]) for row in assets}
        if len(assets) != expected_count or len(identities) != expected_count:
            raise ValueError("formal image manifest is incomplete or has duplicate containers")
        asset_manifest = temporary / "assets/manifest.json"
        write_json(asset_manifest, {"assets": assets})

        master_songs = read_json(master_target / "MasterLiveMusic.json")["_allData"]
        from tools.music_catalog import DIFFICULTIES
        score_rows = {row["_id"]: row for row in read_json(master_target / "MasterLiveMusicScore.json")["_allData"]}
        score_paths = {f"{score_rows[song[field]]['_musicScoreTextFileName']}.bytes"
                       for song in master_songs for _, field in DIFFICULTIES}
        if len(score_paths) != 336:
            raise ValueError("formal Master must reference 336 unique scores")
        payloads = {}
        for logical in score_paths:
            source = SCORES / "raw-score" / logical
            if not source.is_file() or not source.stat().st_size:
                raise ValueError(f"missing verified raw score: {logical}")
            payloads[logical] = source.read_bytes()
        verified_scores = {(int(row["musicIdSuffix"]), int(row["difficulty"])): row
                           for row in score_report["results"] if row.get("regular") and row.get("status") == "validated"}
        for logical, payload in payloads.items():
            music, difficulty = Path(logical).stem.split("_")
            report = verified_scores.get((int(music), int(difficulty)))
            if not report or hashlib.sha256(payload).hexdigest() != report["rawScoreSha256"]:
                raise ValueError(f"raw score digest mismatch: {logical}")
        identity = {"region": "global", "channel": "production", "contentReleaseId": RELEASE_ID}
        score_binding = write_score_inputs(identity, payloads, temporary / "scores")
        baseline = {
            "schemaVersion": 1, "identity": identity,
            "client": {"packageName": provenance["package"], "versionName": provenance["versionName"],
                       "versionCode": provenance["versionCode"], "unityVersion": "6000.3.12f1"},
            "master": {"aggregateSha256": _master_aggregate(table_records)},
            "objects": {"assetManifest": {"sha256": digest(asset_manifest), "byteSize": asset_manifest.stat().st_size},
                        "remoteCatalog": {"sha256": provenance["remoteCatalogSha256"]}},
            "statistics": {"criticalTableRows": rows, "masterTableCount": 240,
                           "jacketCount": 84, "primaryImageCount": 172,
                           "gachaBannerCount": 9, "uiIconCount": 51 if ui_icons else 0,
                           "avatarCount": 25 if avatars else 0, "itemImageCount": item_count, "scoreCount": 336},
            "provenance": provenance,
        }
        write_json(temporary / "content-release.json", baseline)
        report = {"contentReleaseId": RELEASE_ID, "masterTables": 240, "jackets": 84,
                  "primaryImages": 172,
                  "gachaBanners": 9,
                  "uiIcons": 51 if ui_icons else 0,
                  "avatars": 25 if avatars else 0, "itemImages": item_count,
                  "scores": 336, "manifestSha256": digest(temporary / "content-release.json"),
                  "assetManifestSha256": digest(asset_manifest),
                  "scoreIndexSha256": score_binding["sha256"]}
        write_json(temporary / "registration.json", report)
        temporary.rename(output)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/formal-inputs" / f"{RELEASE_ID}-assets-v3")
    parser.add_argument("--ui-icons", type=Path, help="Verified Global UI icon extraction")
    parser.add_argument("--item-images", type=Path, help="Verified Global item image extraction")
    parser.add_argument("--avatars", type=Path, help="Verified Global character face extraction")
    args = parser.parse_args()
    print(json.dumps(register(args.output, ui_icons=args.ui_icons, item_images=args.item_images, avatars=args.avatars), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
