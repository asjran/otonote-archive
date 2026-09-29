"""Refresh existing website inputs from a verified remote snapshot.

New entity families, changed story payloads or changed song audio stop with a
specific coverage error. They never silently inherit a different release's data.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from tools.global_remote_sync import file_hash, read_json, write_json, validate_manifest
from tools.release_preflight import check_environment, load_plan
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.golden import CURRENT_SITE_MASTER_TABLES, _master_aggregate, _master_row_count
from tools.score_inputs import read_score_inputs, write_score_inputs
from tools.story_text import MASTER_TABLES, read_story_inputs
from tools.music_audio_inputs import read_music_audio_inputs

ROOT = Path(__file__).resolve().parents[1]
APK = ROOT / "input/global/apks/2026-09-22-v1.0.1-25/base.apk"
METADATA = ROOT / "input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/global-metadata.v39.dat"


def bundle_stem(name: str) -> str:
    return re.sub(r"_[0-9a-f]{32}\.bundle$", "", name)


def release_id(observation: dict, catalog_sha256: str) -> str:
    # Master-only updates must not share cache URLs with the prior release.
    return (f"global-prod-remote-{observation['resourceVersion'].replace('.', '-')}"
            f"-{catalog_sha256[:8]}-{observation['masterVersion']}")


def bundle_map(catalog) -> dict:
    result = {}
    for row in catalog.locations:
        if row.provider_id.endswith((".AssetBundleProvider", ".AssetBundleCryptProvider")):
            if row.primary_key in result and result[row.primary_key] != row:
                raise ValueError("ambiguous bundle key")
            result[row.primary_key] = row
    return result


def same_bundle(name: str, old: dict, new: dict) -> bool:
    a, b = old.get(name), new.get(name)
    return bool(a and b and (a.internal_id, a.expected_hash, a.expected_size, a.provider_id)
                == (b.internal_id, b.expected_hash, b.expected_size, b.provider_id))


def verified_copy(source: Path, target: Path, expected: str) -> None:
    if not source.is_file() or file_hash(source) != expected:
        raise ValueError(f"source digest mismatch: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if file_hash(target) != expected:
        raise ValueError(f"copied digest mismatch: {target.name}")


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("input path escapes its root")
    return path


def refresh(snapshot: Path, baseline_catalog: Path, plan: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists")
    if (ROOT / "output").resolve() not in output.resolve().parents:
        raise ValueError("formal candidate inputs must be under repository output/")
    source = next(x for x in load_plan(plan) if x["id"] == "global-production")
    if check_environment(source, ROOT)["status"] != "passed":
        raise ValueError("previous website inputs failed preflight")
    baseline = read_json(ROOT / source["manifest"])
    report = read_json(snapshot / "report.json")
    if report.get("status") != "verified_snapshot" or read_json(snapshot / "status.json").get("status") != "verified_snapshot":
        raise ValueError("remote snapshot is incomplete")
    observation = report["observation"]
    if observation["clientVersion"] != baseline["client"]["versionName"]:
        raise ValueError("new client version requires decoder review")
    if file_hash(snapshot / "RemoteCatalog/catalog_main.bin") != report["catalogSha256"]:
        raise ValueError("remote catalog digest mismatch")
    if file_hash(baseline_catalog) != baseline["objects"]["remoteCatalog"]["sha256"]:
        raise ValueError("baseline catalog does not match previous website release")
    if file_hash(snapshot / "Master/MasterManifest.json") != report["masterManifestSha256"]:
        raise ValueError("remote Master manifest digest mismatch")
    master_rows = validate_manifest(read_json(snapshot / "Master/MasterManifest.json"), observation["masterVersion"])
    decrypt_report = read_json(snapshot / "master-json/master-decrypt-report.json")
    decrypted = {Path(row["source"]).name: row for row in decrypt_report["results"]}
    if decrypt_report["failures"] or len(decrypted) != len(master_rows):
        raise ValueError("incomplete Master decryption")
    for row in master_rows:
        clear = snapshot / "master-json" / (Path(row["name"]).stem + ".json")
        if (file_hash(snapshot / "Master" / row["name"]) != row["hash"]
                or decrypted[row["name"]]["encrypted_sha256"] != row["hash"]
                or file_hash(clear) != decrypted[row["name"]]["json_sha256"]):
            raise ValueError("Master source/decryption binding mismatch")
    old_master, new_master = ROOT / source["masterRoot"], snapshot / "master-json"
    # These domains currently use release-specific extraction. Detect coverage
    # changes before copying any bindings, rather than producing a partial site.
    fixed_tables = ("MasterCharacter", "MasterMemberCard", "MasterSupportCard", "MasterLiveMusic", "MasterLiveMusicScore", "MasterItem", "MasterBandItem")
    for name in fixed_tables:
        before, after = read_json(old_master / f"{name}.json")["_allData"], read_json(new_master / f"{name}.json")["_allData"]
        if {x["_id"] for x in before} != {x["_id"] for x in after}:
            raise ValueError(f"website extraction coverage changed: {name}; acquire new entity assets before binding")
    old = bundle_map(CatalogAdapter().parse(baseline_catalog))
    new = bundle_map(CatalogAdapter().parse(snapshot / "RemoteCatalog/catalog_main.bin"))
    by_stem = {}
    for name in new:
        by_stem.setdefault(bundle_stem(name), []).append(name)
    from analysis.crypto.decrypt_global_formal_scores import (
        METADATA_SHA256, KEY_FIELD_USAGE, NONCE_SEED_FIELD_USAGE, MetadataV39,
        UnityPy, field_bytes, decrypt_header,
    )
    if file_hash(METADATA) != METADATA_SHA256 or file_hash(APK) != baseline["provenance"]["apkSha256"]["base.apk"]:
        raise ValueError("decoder or original APK identity changed")
    metadata = MetadataV39(METADATA)
    key, seed = field_bytes(metadata, KEY_FIELD_USAGE, 16), field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    old_assets = read_json(ROOT / source["assetManifest"])["assets"]
    release = release_id(observation, report["catalogSha256"])
    new_source = {**source, "contentReleaseId": release}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".remote-inputs-", dir=output.parent) as tmp:
        stage = Path(tmp)
        table_records = []
        for row in master_rows:
            name = Path(row["name"]).stem + ".json"
            verified_copy(new_master / name, stage / "master" / name, decrypted[row["name"]]["json_sha256"])
            table_records.append({"logicalName": name, "sha256": file_hash(stage / "master" / name)})
        assets, refreshed, cached_env = [], [], {}
        with zipfile.ZipFile(APK) as archive:
            packaged = {Path(name).name for name in archive.namelist() if name.endswith(".bundle")}
        for row in old_assets:
            target = contained(stage / "assets", row["exported_file"])
            original = contained(ROOT / source["extractedRoot"], row["exported_file"])
            name = row["bundle"]
            if same_bundle(name, old, new) or name not in old and name in packaged:
                verified_copy(original, target, row["sha256"])
                assets.append(row)
                continue
            candidates = by_stem.get(bundle_stem(name), [])
            if len(candidates) != 1:
                raise ValueError(f"no unique replacement for {name}")
            replacement = candidates[0]
            location = new[replacement]
            path = snapshot / "assets" / replacement
            receipt = read_json(path.with_name(path.name + ".receipt.json"))
            if (file_hash(path) != receipt["sha256"] or path.stat().st_size != location.expected_size
                    or receipt["url"] != observation["cdnRoot"] + "/asset/Android/" + replacement):
                raise ValueError("replacement bundle receipt mismatch")
            if replacement not in cached_env:
                raw = path.read_bytes()
                clear = decrypt_header(raw, replacement, key, seed) if location.provider_id.endswith(".AssetBundleCryptProvider") else raw
                cached_env[replacement] = UnityPy.load(clear)
            env = cached_env[replacement]
            matches = [obj for container, obj in env.container.items()
                       if container == row["container_path"] and obj.type.name == row["type"]]
            if len(matches) != 1 or matches[0].read().m_Name != row["name"]:
                raise ValueError(f"replacement image object changed: {row['container_path']}")
            obj = matches[0]
            image = obj.read().image
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")
            assets.append({**row, "bundle": replacement, "path_id": obj.path_id, "width": image.width,
                           "height": image.height, "sha256": file_hash(target)})
            refreshed.append({"oldBundle": name, "bundle": replacement, "exportedFile": row["exported_file"]})
        write_json(stage / "assets/manifest.json", {"assets": assets})
        scores = read_score_inputs(source, ROOT)
        if scores is None or any(not same_bundle(name, old, new) for name in old if "_musicscore_" in name):
            raise ValueError("score source changed; score extraction required")
        write_score_inputs(new_source, scores, stage / "scores")
        # ADV documents have their own text bundles; MasterText only changes
        # library names and is consumed again by the website projection.
        read_story_inputs(source, ROOT)
        story_dir = (ROOT / source["storyInputs"]["index"]).parent
        story_report = read_json(story_dir / "report.json")
        if any(not same_bundle(row["bundle"], old, new) for row in story_report["receipts"]):
            raise ValueError("story payload changed; story extraction required")
        for name in MASTER_TABLES:
            if name != "MasterText" and read_json(old_master / f"{name}.json") != read_json(new_master / f"{name}.json"):
                raise ValueError(f"story coverage changed: {name}")
        story_index = read_json(story_dir / "index.json")
        for row in story_index["documents"]:
            verified_copy(contained(story_dir, row["path"]), contained(stage / "stories", row["path"]), row["sha256"])
        story_index.update(sourceReleaseId=release, catalogSha256=report["catalogSha256"],
                           masterSha256={name: file_hash(stage / "master" / f"{name}.json") for name in MASTER_TABLES})
        write_json(stage / "stories/index.json", story_index)
        # Retain source receipts so this newly generated release can itself be a baseline.
        write_json(stage / "stories/report.json", {**story_report, "binding": None})
        audio_path = read_music_audio_inputs(source, ROOT)
        if audio_path:
            audio = read_json(audio_path)
            for row in audio["files"]:
                if not same_bundle(Path(row["source"]).name, old, new):
                    raise ValueError("song audio changed; audio extraction required")
                for stream in row["streams"]:
                    verified_copy(contained(audio_path.parent, stream["output"]), contained(stage / "audio", stream["output"]), stream["sha256"])
            audio["identity"] = {k: new_source[k] for k in ("region", "channel", "contentReleaseId")}
            audio["catalogSha256"] = report["catalogSha256"]
            write_json(stage / "audio/cri-media-report.json", audio)
        manifest = copy.deepcopy(baseline)
        manifest["identity"]["contentReleaseId"] = release
        manifest["master"]["aggregateSha256"] = _master_aggregate(table_records)
        manifest["objects"]["assetManifest"] = {"sha256": file_hash(stage / "assets/manifest.json"), "byteSize": (stage / "assets/manifest.json").stat().st_size}
        manifest["objects"]["remoteCatalog"] = {"sha256": report["catalogSha256"]}
        manifest["statistics"]["criticalTableRows"] = {name: _master_row_count(read_json(stage / "master" / f"{name}.json"), name) for name in CURRENT_SITE_MASTER_TABLES}
        manifest["statistics"]["masterTableCount"] = len(master_rows)
        manifest["provenance"] = {"masterSource": "public_protocol", "remoteSnapshotReport": str((snapshot / "report.json").resolve().relative_to(ROOT)),
                                  "remoteSnapshotReportSha256": file_hash(snapshot / "report.json"), "remoteCatalogSha256": report["catalogSha256"],
                                  "masterManifestSha256": report["masterManifestSha256"], "priorContentReleaseId": source["contentReleaseId"],
                                  "apkSha256": baseline["provenance"]["apkSha256"], "remoteCodeChanged": report["remoteCodeChanged"]}
        write_json(stage / "content-release.json", manifest)
        def final_path(relative):
            return (output.resolve() / relative).relative_to(ROOT).as_posix()
        new_source.update(manifest=final_path("content-release.json"), manifestSha256=file_hash(stage / "content-release.json"),
                          masterRoot=final_path("master"), assetManifest=final_path("assets/manifest.json"), extractedRoot=final_path("assets"),
                          scoreInputs={"index": final_path("scores/index.json"), "sha256": file_hash(stage / "scores/index.json")},
                          storyInputs={"index": final_path("stories/index.json"), "sha256": file_hash(stage / "stories/index.json")})
        if audio_path:
            new_source["musicAudioInputs"] = {"report": final_path("audio/cri-media-report.json"), "sha256": file_hash(stage / "audio/cri-media-report.json")}
        write_json(stage / "release-inputs.json", {"schemaVersion": 1, "environments": [new_source]})
        summary = {"contentReleaseId": release, "masterTables": len(master_rows), "images": len(assets),
                   "refreshedImages": len(refreshed), "scores": len(scores), "stories": len(story_index["documents"]),
                   "remoteCodeChanged": report["remoteCodeChanged"], "publicationReady": False,
                   "plan": final_path("release-inputs.json"), "refreshed": refreshed}
        write_json(stage / "refresh-report.json", summary)
        stage.rename(output)
    if check_environment(new_source, ROOT)["status"] != "passed":
        raise ValueError("new input preflight failed; candidate not ready")
    return {k: v for k, v in summary.items() if k != "refreshed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--baseline-catalog", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/release-inputs.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(refresh(args.snapshot, args.baseline_catalog, args.plan, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
