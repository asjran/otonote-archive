#!/usr/bin/env python3
"""Read the audited production constants directly from the original ARM64 APK.

libanort 0x13e624 decrypts the first 0x4000 bytes in 0x800-byte CBC chunks.
The embedded configuration at 0x1cbe50, decoded by 0x30a1c, supplies ba981955;
0x13e648 formats it twice as hexadecimal. The IV lives at 0x190060.
This is a release-pinned data extraction, not an Android runtime replacement.
"""
import hashlib
import json
import struct
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APK = ROOT / "input/global/apks/2026-09-22-v1.0.1-25/split_config.arm64_v8a.apk"
NATIVE_HASH = "514a5b73d038c264b60cc91fd4a747cf178190c6b2096e6d7007c2020e2b1bca"
LOADER_HASH = "2a36573bfe4069a7fb19de091e1d59e2a5806738a47be02881f6d6bf1d058e88"


def extract(apk: Path = APK) -> dict:
    with zipfile.ZipFile(apk) as archive:
        native = archive.read("lib/arm64-v8a/libil2cpp.so")
        loader = archive.read("lib/arm64-v8a/libanort.so")
    if hashlib.sha256(native).hexdigest() != NATIVE_HASH or hashlib.sha256(loader).hexdigest() != LOADER_HASH:
        raise ValueError("Package does not match the audited production profile")
    # libanort's third PT_LOAD has a 0x8000 VA/file offset difference.
    iv = loader[0x190060 - 0x8000:0x190070 - 0x8000]
    if iv.hex() != "02030405060708090a0b0c0d0e0f1011":
        raise ValueError("Unexpected production AES IV")
    decoded = subprocess.run([
        "openssl", "enc", "-d", "-aes-128-cbc", "-nopad",
        "-K", b"ba981955ba981955".hex(), "-iv", iv.hex(),
    ], input=native[0x1ffc000:0x1ffc800], capture_output=True, check=True).stdout
    value = struct.unpack_from("<f", decoded, 0x24)[0]
    if decoded[0x24:0x28].hex() != "0ad7a33b":
        raise ValueError("Native difficulty constant failed its byte-level audit")
    luck_chunk = subprocess.run([
        "openssl", "enc", "-d", "-aes-128-cbc", "-nopad",
        "-K", b"ba981955ba981955".hex(), "-iv", iv.hex(),
    ], input=native[0x1ffc800:0x1ffd000], capture_output=True, check=True).stdout
    luck_types = list(struct.unpack_from("<4i", luck_chunk, 0x320))
    luck_points = list(struct.unpack_from("<3i", native, 0x20612f0))
    if luck_types != [0, 4, 3, 2] or luck_points != [5, 10, 10]:
        raise ValueError("Unexpected native LuckScore lookup tables")
    return {
        "sourceReleaseId": "global-prod-20260924-v1-0-1-25-39b5d81f",
        "nativeSha256": NATIVE_HASH, "loaderSha256": LOADER_HASH,
        "difficultyIncrement": value,
        "difficultyIncrementBits": "3ba3d70a",
        "difficultyMethodAddress": "0x55e166c",
        "difficultyConstantAddress": "0x1ffc024",
        "skillValueDivisor": struct.unpack_from("<f", native, 0x1ffbfe0)[0],
        "tickMillisecondsPerMinute": struct.unpack_from("<d", native, 0x1ffa588)[0],
        "luckChanceTypesByRushCombo": luck_types,
        "luckChanceTypeAfterThreeRushes": 1,
        "luckPointsByResult": [0, *luck_points],
        "luckChanceTypeTableAddress": "0x1ffcb20",
        "luckPointTableAddress": "0x20612f0",
        "verification": "native_loader_emulation_and_independent_openssl_decode",
    }


if __name__ == "__main__":
    result = extract()
    output = ROOT / "site/src/data/formal-scoring-native.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
