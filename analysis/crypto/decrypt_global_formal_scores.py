#!/usr/bin/env python3
"""Validate cached Global 1.0.1 music score bundles against the captured catalog.

The metadata field references and 16 KiB encrypted header are verified from the
2026-09-22 Global production IL2CPP binary. Key material stays in memory.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis/.deps"))

from analysis.crypto.inspect_il2cpp import MetadataV39
from tools.resource_pipeline.catalog_adapter import CatalogAdapter

try:
    import UnityPy
except ImportError as exc:
    raise SystemExit("UnityPy is required in analysis/.deps") from exc


METADATA_SHA256 = "4cbc7d02989c6af496cc33966d03ab01e1200579b1be479c433a8cf61d4b2e0b"
CATALOG_SHA256 = "39b5d81ff337bfe0ef0af668f5b473a18e20aa1f8ce6d1c18ca4d6ffe0583c65"
KEY_FIELD_USAGE = 0x800001E7
NONCE_SEED_FIELD_USAGE = 0x800001EF
ENCRYPTED_HEADER_SIZE = 16 * 1024
REGULAR_SCORE = re.compile(r"^live_assets_live_musicscore_(\d{4})_\1_(\d{2})_[0-9a-f]{32}\.bundle$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def field_bytes(metadata: MetadataV39, usage: int, length: int) -> bytes:
    """Resolve an IL2CPP FieldRef usage to its FieldRVA default bytes."""
    index = (usage & 0x1FFFFFFF) >> 1
    refs_offset, _, refs_count = metadata.sections[22]
    if index >= refs_count:
        raise ValueError("FieldRef usage is outside metadata")
    type_index, local_field = struct.unpack_from("<II", metadata.data, refs_offset + index * 8)
    owners = [
        i for i in range(metadata.type_count)
        if struct.unpack_from("<I", metadata.data, metadata.type_offset + i * 82 + 8)[0] == type_index
    ]
    if len(owners) != 1 or metadata.type_name(owners[0]) != "<PrivateImplementationDetails>":
        raise ValueError("FieldRef owner is not the expected private implementation type")
    # v39 TypeDefinition fieldStart is at byte 26 in its 82-byte record.
    field_start = struct.unpack_from("<I", metadata.data, metadata.type_offset + owners[0] * 82 + 26)[0]
    field_index = field_start + local_field
    defaults_offset, _, defaults_count = metadata.sections[7]
    matches = [
        data_index
        for i in range(defaults_count)
        for current, _, data_index in (struct.unpack_from("<III", metadata.data, defaults_offset + i * 12),)
        if current == field_index
    ]
    if len(matches) != 1:
        raise ValueError("FieldRef has no unique default value")
    data_offset, data_size, _ = metadata.sections[8]
    if matches[0] + length > data_size:
        raise ValueError("FieldRef default value exceeds the data section")
    return metadata.data[data_offset + matches[0]:data_offset + matches[0] + length]


def decrypt_header(payload: bytes, bundle_name: str, key: bytes, nonce_seed: bytes) -> bytes:
    nonce = hashlib.sha256(nonce_seed + bundle_name.encode("utf-8")).digest()[:8]
    count = min(len(payload), ENCRYPTED_HEADER_SIZE)
    blocks = (count + 15) // 16
    counter_input = b"".join(nonce + index.to_bytes(8, "big") for index in range(blocks))
    result = subprocess.run(
        ["openssl", "enc", "-aes-128-ecb", "-K", key.hex(), "-nopad", "-nosalt"],
        input=counter_input, capture_output=True,
    )
    if result.returncode or len(result.stdout) != len(counter_input):
        raise ValueError("AES keystream generation failed")
    clear = bytes(a ^ b for a, b in zip(payload[:count], result.stdout)) + payload[count:]
    if not clear.startswith(b"UnityFS\0"):
        raise ValueError("decrypted payload does not have a UnityFS header")
    return clear


def text_payload(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8", errors="surrogateescape")
    return bytes(value)


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
    metadata = MetadataV39(args.metadata)
    key = field_bytes(metadata, KEY_FIELD_USAGE, 16)
    seed = field_bytes(metadata, NONCE_SEED_FIELD_USAGE, 8)
    catalog = CatalogAdapter().parse(catalog_path)
    bundle_by_id = {
        location.primary_key[:-7].rsplit("_", 1)[-1]: location
        for location in catalog.locations
        if location.provider_id.endswith(".AssetBundleCryptProvider")
        and location.primary_key.endswith(".bundle")
    }
    master = json.loads((args.master_root / "MasterLiveMusic.json").read_text(encoding="utf-8"))
    music_ids = {row["_id"] % 100000 for row in master["_allData"]}
    if len(music_ids) != 84:
        parser.error("expected 84 unique formal music IDs")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.output.name}-", dir=args.output.parent))
    results = []
    observed = set()
    try:
        for path in sorted((args.capture_root / "EncryptedBundles").glob("*musicscore*")):
            relative = path.relative_to(args.capture_root).as_posix()
            row = recorded.get(relative)
            if not row or path.stat().st_size != row["size_bytes"] or sha256(path) != row["sha256"]:
                raise ValueError(f"device capture digest mismatch: {path.name}")
            identifier = path.name.split("_", 1)[0]
            location = bundle_by_id.get(identifier)
            if location is None or location.expected_size != path.stat().st_size:
                raise ValueError(f"catalog location mismatch: {path.name}")
            match = REGULAR_SCORE.fullmatch(location.primary_key)
            record = {"bundle": location.primary_key, "encryptedSha256": row["sha256"],
                      "regular": bool(match), "status": "unverified"}
            try:
                clear = decrypt_header(path.read_bytes(), location.primary_key, key, seed)
                environment = UnityPy.load(clear)
                assets = [obj for obj in environment.objects if obj.type.name == "TextAsset"]
                if not assets:
                    raise ValueError("UnityFS has no TextAsset")
                parsed = []
                for asset in assets:
                    data = asset.read()
                    raw_score = text_payload(data.m_Script)
                    document = json.loads(gzip.decompress(raw_score))
                    if not isinstance(document, dict) or not isinstance(document.get("score"), dict):
                        raise ValueError("TextAsset has no score object")
                    parsed.append((str(data.m_Name), document, raw_score))
                if match:
                    if len(parsed) != 1:
                        raise ValueError("regular score bundle has multiple TextAssets")
                    music_id, difficulty = int(match.group(1)), int(match.group(2))
                    if difficulty not in range(4):
                        raise ValueError("regular score has an unexpected difficulty")
                    output = temporary / "score-json" / f"{music_id:04d}" / f"{difficulty:02d}.json"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps(parsed[0][1], ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                    raw_output = temporary / "raw-score" / f"{music_id:04d}" / f"{music_id:04d}_{difficulty:02d}.bytes"
                    raw_output.parent.mkdir(parents=True, exist_ok=True)
                    raw_output.write_bytes(parsed[0][2])
                    observed.add((music_id, difficulty))
                    record.update({"musicIdSuffix": music_id, "difficulty": difficulty,
                                   "scoreJsonSha256": sha256(output), "rawScoreSha256": sha256(raw_output)})
                record.update({"status": "validated", "textAssets": [name for name, _, _ in parsed],
                               "decryptedBundleSha256": hashlib.sha256(clear).hexdigest()})
            except Exception as exc:
                record.update({
                    "status": "failed" if match else "nonregular_unparsed",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            results.append(record)
        expected = {(music_id, difficulty) for music_id in music_ids for difficulty in range(4)}
        missing = sorted(expected - observed)
        summary = {
            "schemaVersion": 1, "package": "com.bilibili.sirius", "version": "1.0.1 (25)",
            "metadataSha256": METADATA_SHA256, "catalogSha256": CATALOG_SHA256,
            "musicCount": len(music_ids), "expectedRegularScores": len(expected),
            "validatedRegularScores": len(expected & observed),
            "extraRegularScores": sorted({music_id for music_id, _ in observed} - music_ids),
            "missing": [{"musicIdSuffix": music_id, "difficulty": difficulty} for music_id, difficulty in missing],
            "processedBundles": len(results), "validatedBundles": sum(row["status"] == "validated" for row in results),
            "failedBundles": sum(row["status"] == "failed" for row in results),
            "nonregularUnparsed": sum(row["status"] == "nonregular_unparsed" for row in results),
            "results": results,
        }
        (temporary / "validation.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        temporary.rename(args.output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(json.dumps({key: value for key, value in summary.items() if key not in ("results", "missing")},
                     ensure_ascii=False, sort_keys=True))
    return 0 if not missing and summary["failedBundles"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
