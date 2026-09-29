"""Build an isolated Global production catalog from verified Master tables only.

This intentionally produces metadata, not a publishable site or score/media data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.master_catalog import build_master_entities, load_master_data
from tools.resource_pipeline.localization import (
    SUPPORTED_LOCALES,
    extract_localized_text,
    resolve_localized_text,
)


class CandidateError(ValueError):
    pass


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateError(f"expected JSON object: {path}")
    return value


def table(root: Path, name: str) -> list[dict]:
    rows = read_json(root / f"{name}.json").get("_allData")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CandidateError(f"invalid Master table: {name}")
    return rows


def unique(rows: list[dict], field: str, label: str) -> dict:
    result = {}
    for row in rows:
        key = row.get(field)
        if key is None or key in result:
            raise CandidateError(f"missing or duplicate {label} {field}: {key!r}")
        result[key] = row
    return result


def verify_inputs(capture_root: Path, master_root: Path) -> dict:
    capture = read_json(capture_root / "capture.json")
    if (capture.get("package"), capture.get("version_name"), capture.get("version_code")) != (
        "com.bilibili.sirius", "1.0.1", 25
    ):
        raise CandidateError("capture is not the expected Global production package")
    files = capture.get("files")
    if not isinstance(files, list) or {item.get("name") for item in files} != {
        "base.apk", "split_config.arm64_v8a.apk"
    }:
        raise CandidateError("capture split set is incomplete")
    for item in files:
        path = capture_root / item["name"]
        if path.stat().st_size != item.get("size_bytes") or digest(path) != item.get("sha256"):
            raise CandidateError(f"capture digest mismatch: {path.name}")

    device_root = capture_root.parent.parent / "device-files" / capture_root.name / "Master"
    manifest_path = device_root / "MasterManifest.json"
    manifest = read_json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 240:
        raise CandidateError("expected 240 verified Master files")
    with ZipFile(capture_root / "base.apk") as apk:
        if apk.read("assets/Master/MasterManifest.json") != manifest_path.read_bytes():
            raise CandidateError("device Master manifest differs from captured APK")
        for entry in entries:
            name = entry.get("name")
            if not isinstance(name, str) or Path(name).name != name or not name.endswith(".bin"):
                raise CandidateError(f"unsafe Master filename: {name!r}")
            binary = device_root / name
            if binary.stat().st_size != entry.get("size") or digest(binary) != entry.get("hash"):
                raise CandidateError(f"Master manifest mismatch: {name}")
            if apk.read(f"assets/Master/{name}") != binary.read_bytes():
                raise CandidateError(f"Master file differs from APK: {name}")
            if not (master_root / f"{Path(name).stem}.json").is_file():
                raise CandidateError(f"decrypted Master table missing: {name}")
    decrypt_report = read_json(master_root / "master-decrypt-report.json")
    if decrypt_report.get("success_count") != 240 or decrypt_report.get("failure_count") != 0:
        raise CandidateError("Master decryption report is incomplete")
    reported = {
        Path(result["source"]).name: result
        for result in decrypt_report.get("results", [])
    }
    if set(reported) != {entry["name"] for entry in entries}:
        raise CandidateError("Master decryption report does not match the package")
    for name, result in reported.items():
        if result.get("encrypted_sha256") != digest(device_root / name):
            raise CandidateError(f"decryption source mismatch: {name}")
        if result.get("json_sha256") != digest(master_root / f"{Path(name).stem}.json"):
            raise CandidateError(f"decrypted JSON mismatch: {name}")
    return {
        "package": capture["package"],
        "versionName": capture["version_name"],
        "versionCode": capture["version_code"],
        "captureManifestSha256": digest(capture_root / "capture.json"),
        "masterManifestSha256": digest(manifest_path),
        "apkSha256": {item["name"]: item["sha256"] for item in files},
    }


def verify_device_inputs(capture_root: Path, device_root: Path, master_root: Path) -> dict:
    """Verify downloaded Master against its device snapshot and the installed APK identity."""
    package = read_json(capture_root / "capture.json")
    if (package.get("package"), package.get("version_name"), package.get("version_code")) != (
        "com.bilibili.sirius", "1.0.1", 25
    ):
        raise CandidateError("APK capture is not the expected Global production package")
    apk_files = package.get("files")
    if not isinstance(apk_files, list) or {item.get("name") for item in apk_files} != {
        "base.apk", "split_config.arm64_v8a.apk"
    }:
        raise CandidateError("APK capture split set is incomplete")
    for item in apk_files:
        path = capture_root / item["name"]
        if path.stat().st_size != item.get("size_bytes") or digest(path) != item.get("sha256"):
            raise CandidateError(f"APK capture digest mismatch: {path.name}")

    capture_path = device_root / "capture.json"
    capture = read_json(capture_path)
    if (capture.get("package"), capture.get("version_name"), capture.get("version_code")) != (
        package["package"], package["version_name"], package["version_code"]
    ):
        raise CandidateError("device capture and APK package identity differ")
    files = capture.get("files")
    if not isinstance(files, list) or not files:
        raise CandidateError("device resource capture is incomplete")
    recorded = {}
    for item in files:
        if not isinstance(item, dict):
            raise CandidateError("invalid device capture entry")
        relative = item.get("path")
        if not isinstance(relative, str):
            raise CandidateError("invalid device capture path")
        path = Path(relative)
        if (not path.parts or path.is_absolute() or ".." in path.parts
                or relative != path.as_posix() or relative in recorded):
            raise CandidateError(f"unsafe or duplicate device capture path: {relative}")
        if path.parts[0] not in {"RemoteCatalog", "Master", "Addressables", "EncryptedBundles"}:
            raise CandidateError(f"unexpected device resource directory: {relative}")
        recorded[relative] = item
        source = device_root / path
        if source.stat().st_size != item.get("size_bytes") or digest(source) != item.get("sha256"):
            raise CandidateError(f"device resource capture mismatch: {relative}")
    actual = {
        path.relative_to(device_root).as_posix()
        for directory in ("RemoteCatalog", "Master", "Addressables", "EncryptedBundles")
        for path in (device_root / directory).rglob("*") if path.is_file()
    }
    if actual != set(recorded):
        raise CandidateError("device resource capture file set differs from local snapshot")

    manifest_path = device_root / "Master/MasterManifest.json"
    manifest = read_json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 240:
        raise CandidateError("expected 240 downloaded Master files")
    if any(not isinstance(entry, dict) for entry in entries):
        raise CandidateError("invalid downloaded Master manifest entry")
    if len({entry.get("name") for entry in entries}) != 240:
        raise CandidateError("duplicate downloaded Master filename")
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".bin"):
            raise CandidateError(f"unsafe downloaded Master filename: {name!r}")
        binary = device_root / "Master" / name
        if binary.stat().st_size != entry.get("size") or digest(binary) != entry.get("hash"):
            raise CandidateError(f"downloaded Master manifest mismatch: {name}")
        if not (master_root / f"{Path(name).stem}.json").is_file():
            raise CandidateError(f"decrypted Master table missing: {name}")
    report = read_json(master_root / "master-decrypt-report.json")
    if report.get("success_count") != 240 or report.get("failure_count") != 0:
        raise CandidateError("downloaded Master decryption report is incomplete")
    reported = {Path(result["source"]).name: result for result in report.get("results", [])}
    if set(reported) != {entry["name"] for entry in entries}:
        raise CandidateError("downloaded Master decryption report has the wrong file set")
    for name, result in reported.items():
        if result.get("encrypted_sha256") != digest(device_root / "Master" / name):
            raise CandidateError(f"downloaded Master decryption source mismatch: {name}")
        if result.get("json_sha256") != digest(master_root / f"{Path(name).stem}.json"):
            raise CandidateError(f"downloaded Master JSON mismatch: {name}")
    return {
        "package": package["package"], "versionName": package["version_name"],
        "versionCode": package["version_code"], "masterSource": "device_download",
        "apkCaptureManifestSha256": digest(capture_root / "capture.json"),
        "resourceCaptureManifestSha256": digest(capture_path),
        "masterManifestSha256": digest(manifest_path),
        "remoteCatalogSha256": digest(device_root / "RemoteCatalog/catalog_main.bin"),
        "apkSha256": {item["name"]: item["sha256"] for item in apk_files},
    }


def project_entities(entities: dict) -> dict:
    return {
        "bands": [
            {key: row[key] for key in ("id", "masterId", "displayName", "localizedText", "characterIds", "mainColor", "subColor")}
            for row in entities["bands"]
        ],
        "characters": [
            {key: row[key] for key in ("id", "masterId", "displayName", "localizedText", "bandId", "memberCardIds", "featuredSupportCardIds")}
            for row in entities["characters"]
        ],
        "memberCards": [
            {key: row[key] for key in ("id", "masterId", "assetId", "displayName", "localizedText", "characterId", "rarity", "attributeCode", "performancePowerMax", "technicPowerMax", "visualPowerMax", "startAt")}
            for row in entities["memberCards"]
        ],
        "supportCards": [
            {key: row[key] for key in ("id", "masterId", "assetId", "displayName", "localizedText", "featuredCharacterIds", "rarity", "attributeCode", "performancePowerMax", "technicPowerMax", "visualPowerMax", "startAt")}
            for row in entities["supportCards"]
        ],
    }


def build_songs(root: Path, texts: dict, band_ids: set[int], locale: str,
                score_payload_status: str = "not_collected") -> tuple[list[dict], set[str]]:
    songs = unique(table(root, "MasterLiveMusic"), "_id", "song")
    scores = unique(table(root, "MasterLiveMusicScore"), "_id", "score")
    live_characters = unique(table(root, "MasterLiveCharacter"), "_characterID", "live character")
    projected = []
    title_keys = set()
    for music_id, row in sorted(songs.items()):
        title_key = row.get("_titleTextID")
        if not isinstance(title_key, str) or title_key not in texts:
            raise CandidateError(f"song {music_id} has no title text")
        title_keys.add(title_key)
        bands = row.get("_bandIDs")
        vocalists = row.get("_vocalCharacterIDs")
        if not isinstance(bands, list) or any(band not in band_ids for band in bands):
            raise CandidateError(f"song {music_id} references an unknown band")
        if not isinstance(vocalists, list) or any(item not in live_characters for item in vocalists):
            raise CandidateError(f"song {music_id} references an unknown live character")
        difficulty_ids = {}
        for difficulty in ("easy", "normal", "hard", "expert"):
            score_id = row.get(f"_{difficulty}ID")
            if score_id not in scores:
                raise CandidateError(f"song {music_id} missing {difficulty} score metadata")
            difficulty_ids[difficulty] = score_id
        localized = extract_localized_text(texts[title_key])
        resolved = resolve_localized_text(texts[title_key], locale)
        if not resolved.text:
            raise CandidateError(f"song {music_id} has no usable title")
        projected.append({
            "id": f"music-{music_id}", "masterId": music_id,
            "displayName": resolved.text, "localizedText": localized,
            "displayLocale": resolved.actual_locale, "usedFallback": resolved.used_fallback,
            "bandIds": [f"band-{band}" for band in bands],
            "liveCharacterIds": vocalists, "difficultyIds": difficulty_ids,
            "startAt": row.get("_startAt"), "scorePayloadStatus": score_payload_status,
        })
    return projected, title_keys


def text_coverage(texts: dict, keys: set[str], locale: str) -> dict:
    missing = sorted(key for key in keys if key not in texts)
    available = keys - set(missing)
    resolved = {key: resolve_localized_text(texts[key], locale) for key in available}
    return {
        "referencedTextIds": len(keys), "missingTextIds": missing,
        "officialLocaleCount": sum(locale in extract_localized_text(texts[key]) for key in available),
        "fallbackTextIds": sorted(key for key, item in resolved.items() if item.used_fallback),
        "fallbackCount": sum(item.used_fallback for item in resolved.values()),
        "unresolvedCount": sum(not item.text for item in resolved.values()),
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def historical_comparison(master_root: Path, historical_root: Path) -> dict:
    names = (
        "MasterBand", "MasterCharacter", "MasterMemberCard", "MasterSupportCard",
        "MasterLiveMusic", "MasterText",
    )
    tables = {}
    for name in names:
        old = unique(table(historical_root, name), "_id", name)
        current = unique(table(master_root, name), "_id", name)
        common = old.keys() & current.keys()
        entry = {
            "oldRows": len(old), "currentRows": len(current),
            "commonIds": len(common), "addedIds": len(current.keys() - old.keys()),
            "removedIds": len(old.keys() - current.keys()),
            "changedCommonIds": sum(old[key] != current[key] for key in common),
        }
        if name == "MasterText":
            entry["oldNumericIds"] = sum(str(key).isdigit() for key in old)
            entry["currentNumericIds"] = sum(str(key).isdigit() for key in current)
        tables[name] = entry
    return {
        "schemaVersion": 1, "baseline": "global-staging-0.3.2-12",
        "purpose": "audit_only_not_candidate_source", "tables": tables,
    }


def build(capture_root: Path, master_root: Path, output: Path,
          historical_root: Path | None = None, device_capture_root: Path | None = None) -> dict:
    if output.exists() or output.is_symlink():
        raise CandidateError("output already exists; choose a new candidate path")
    output = output.resolve()
    if not output.is_relative_to(ROOT / "output"):
        raise CandidateError("candidate output must be inside the isolated output directory")
    source = (
        verify_device_inputs(capture_root, device_capture_root, master_root)
        if device_capture_root is not None else verify_inputs(capture_root, master_root)
    )
    master = load_master_data(master_root)
    band_ids = set(master.bands)
    text_keys = {
        key for rows, fields in (
            (master.bands.values(), ("_nameTextID", "_descriptionTextID")),
            (master.characters.values(), ("_nameTextID", "_shortNameTextID", "_enDisplayNameTextId")),
            (master.member_cards.values(), ("_nameTextID", "_subtitleTextID")),
            (master.support_cards.values(), ("_nameTextID", "_descriptionTextID")),
        ) for row in rows for field in fields
        if isinstance((key := row.get(field)), str) and key
    }
    outputs = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for locale in SUPPORTED_LOCALES:
            entities, _ = build_master_entities(master, [], {}, "global-production-v1.0.1-25", locale)
            songs, title_keys = build_songs(
                master_root, master.texts, band_ids, locale,
                "cached_unverified" if device_capture_root is not None else "not_collected",
            )
            catalog = {
                "schemaVersion": 1, "status": "master_metadata_candidate",
                "region": "global", "channel": "production", "locale": locale,
                **project_entities(entities), "musicTracks": songs,
            }
            write_json(candidate / f"catalog-{locale}.json", catalog)
            outputs[locale] = {
                "bands": len(catalog["bands"]), "characters": len(catalog["characters"]),
                "memberCards": len(catalog["memberCards"]), "supportCards": len(catalog["supportCards"]),
                "musicTracks": len(songs),
                "scoreMetadataReferences": len(songs) * 4,
                "textCoverage": text_coverage(master.texts, text_keys | title_keys, locale),
                "sha256": digest(candidate / f"catalog-{locale}.json"),
            }
        report = {
            "schemaVersion": 1, "status": "candidate_generated", "publicationReady": False,
            "source": source, "locales": outputs,
            "limitations": [
                "media_not_bound" if device_capture_root is not None else "media_not_collected",
                "music_score_payload_not_validated" if device_capture_root is not None else "music_score_payload_not_collected",
                "event_table_empty", "jp_production_input_not_bound",
                "cross_region_ids_not_validated", "site_build_not_run",
            ],
        }
        if historical_root is not None:
            comparison = historical_comparison(master_root, historical_root)
            write_json(candidate / "historical-comparison.json", comparison)
            report["historicalComparisonSha256"] = digest(candidate / "historical-comparison.json")
        write_json(candidate / "validation.json", report)
        if output.exists():
            raise CandidateError("candidate output appeared during generation")
        candidate.rename(output)
        return report
    finally:
        if candidate.exists():
            shutil.rmtree(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--device-capture-root", type=Path,
                        help="verified post-launch device resource snapshot")
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--historical-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.capture_root, args.master_root, args.output,
                       args.historical_root, args.device_capture_root)
    except (CandidateError, OSError, ValueError) as exc:
        parser.exit(1, f"Candidate generation failed: {exc}\n")
    print(json.dumps({"status": result["status"], "publicationReady": result["publicationReady"], "locales": result["locales"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
