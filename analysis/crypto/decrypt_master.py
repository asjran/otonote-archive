#!/usr/bin/env python3
"""Decrypt the game's Rijndael-protected JSON files."""

from __future__ import annotations

import argparse
import os
import gzip
import hashlib
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR.parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from py3rijndael import Rijndael
except ImportError as error:
    raise SystemExit(
        "py3rijndael is required. Install analysis dependencies with:\n"
        "python3 -m pip install --target analysis/vendor "
        "-r analysis/requirements.txt"
    ) from error


BLOCK_SIZE = 32
HEADER_SIZE = 64
DEFAULT_SALT = bytes.fromhex(os.environ.get("OURNOTES_MASTER_SALT_HEX", ""))
DEFAULT_KEY = bytes.fromhex(os.environ.get("OURNOTES_MASTER_KEY_HEX", ""))
DEFAULT_IV = bytes.fromhex(os.environ.get("OURNOTES_MASTER_IV_HEX", ""))


def parse_hex_32(value: str) -> bytes:
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected hexadecimal bytes") from error
    if len(decoded) != BLOCK_SIZE:
        raise argparse.ArgumentTypeError("expected exactly 32 bytes")
    return decoded


def decrypt_cbc(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if not ciphertext or len(ciphertext) % BLOCK_SIZE:
        raise ValueError("ciphertext length is not a positive multiple of 32")

    cipher = Rijndael(key=key, block_size=BLOCK_SIZE)
    plaintext = bytearray()
    previous = iv
    for offset in range(0, len(ciphertext), BLOCK_SIZE):
        block = ciphertext[offset : offset + BLOCK_SIZE]
        decrypted = cipher.decrypt(block)
        plaintext.extend(left ^ right for left, right in zip(decrypted, previous))
        previous = block

    padding_size = plaintext[-1]
    if not 1 <= padding_size <= BLOCK_SIZE:
        raise ValueError(f"invalid PKCS7 padding size: {padding_size}")
    if plaintext[-padding_size:] != bytes([padding_size]) * padding_size:
        raise ValueError("invalid PKCS7 padding bytes")
    return bytes(plaintext[:-padding_size])


def decode_json_payload(plaintext: bytes) -> tuple[bytes, str]:
    if plaintext.startswith(b"\x1f\x8b"):
        return gzip.decompress(plaintext), "gzip-json"
    return plaintext, "raw-json"


def decrypt_master_file(
    source: Path,
    destination: Path,
    *,
    salt: bytes,
    key: bytes,
    iv: bytes,
) -> dict[str, object]:
    if any(len(value) != BLOCK_SIZE for value in (salt, key, iv)):
        raise ValueError("Configure private OURNOTES_MASTER_SALT_HEX, OURNOTES_MASTER_KEY_HEX and OURNOTES_MASTER_IV_HEX (32 bytes each)")
    encrypted = source.read_bytes()
    if len(encrypted) < HEADER_SIZE + BLOCK_SIZE:
        raise ValueError("file is too small to contain a Master payload")

    actual_salt = encrypted[:BLOCK_SIZE]
    actual_iv = encrypted[BLOCK_SIZE:HEADER_SIZE]
    if actual_salt != salt:
        raise ValueError("Master salt/header does not match this package")
    if actual_iv != iv:
        raise ValueError("Master IV/header does not match this package")

    plaintext = decrypt_cbc(encrypted[HEADER_SIZE:], key, iv)
    json_bytes, payload_encoding = decode_json_payload(plaintext)
    parsed = json.loads(json_bytes)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(json_bytes)
    return {
        "source": str(source),
        "output": str(destination),
        "encrypted_size": len(encrypted),
        "plaintext_size": len(plaintext),
        "json_size": len(json_bytes),
        "json_root_type": type(parsed).__name__,
        "payload_encoding": payload_encoding,
        "encrypted_sha256": hashlib.sha256(encrypted).hexdigest(),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
        "json_sha256": hashlib.sha256(json_bytes).hexdigest(),
    }


def collect_inputs(
    source: Path,
    *,
    all_matching: bool,
    salt: bytes,
    iv: bytes,
) -> tuple[Path, list[Path]]:
    if source.is_file():
        return source.parent, [source]
    if source.is_dir():
        if not all_matching:
            return source, sorted(source.rglob("*.bin"))

        header = salt + iv
        matching = []
        for candidate in source.rglob("*"):
            if not candidate.is_file() or candidate.stat().st_size < HEADER_SIZE:
                continue
            with candidate.open("rb") as stream:
                if stream.read(HEADER_SIZE) == header:
                    matching.append(candidate)
        return source, sorted(matching)
    raise FileNotFoundError(source)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decrypt Rijndael-protected Master JSON files."
    )
    parser.add_argument("input", type=Path, help="a Master .bin file or directory")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--salt", type=parse_hex_32, default=DEFAULT_SALT.hex())
    parser.add_argument("--key", type=parse_hex_32, default=DEFAULT_KEY.hex())
    parser.add_argument("--iv", type=parse_hex_32, default=DEFAULT_IV.hex())
    parser.add_argument(
        "--all-matching",
        action="store_true",
        help="decrypt every file whose 64-byte header matches, regardless of extension",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="report path; defaults to OUTPUT_DIR/master-decrypt-report.json",
    )
    args = parser.parse_args()

    input_root, inputs = collect_inputs(
        args.input,
        all_matching=args.all_matching,
        salt=args.salt,
        iv=args.iv,
    )
    if not inputs:
        expected = "matching encrypted files" if args.all_matching else ".bin files"
        raise ValueError(f"no {expected} found")

    results = []
    failures = []
    for source in inputs:
        relative = source.relative_to(input_root).with_suffix(".json")
        destination = args.output_dir / relative
        try:
            results.append(
                decrypt_master_file(
                    source,
                    destination,
                    salt=args.salt,
                    key=args.key,
                    iv=args.iv,
                )
            )
        except Exception as error:
            failures.append(
                {
                    "source": str(source),
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    report = {
        "algorithm": "Rijndael-256-CBC-PKCS7",
        "header_size": HEADER_SIZE,
        "block_size": BLOCK_SIZE,
        "crypto_material": "provided-and-redacted",
        "success_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "failures": failures,
    }
    report_path = args.report or args.output_dir / "master-decrypt-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "algorithm": report["algorithm"],
                "success_count": report["success_count"],
                "failure_count": report["failure_count"],
            },
            ensure_ascii=False,
        )
    )
    print(f"report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
