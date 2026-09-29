#!/usr/bin/env python3
"""Restore an XOR-obfuscated IL2CPP global metadata file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


IL2CPP_MAGIC = bytes.fromhex("AF1BB1FA")


def decode(source: bytes, key: int, version: int) -> bytes:
    decoded = bytearray(value ^ key for value in source)
    decoded[:4] = IL2CPP_MAGIC
    decoded[4:8] = version.to_bytes(4, "little")
    return bytes(decoded)


def validate_triplet_header(decoded: bytes) -> dict[str, object]:
    if len(decoded) < 12:
        raise ValueError("metadata file is too small")

    header_size = int.from_bytes(decoded[8:12], "little")
    if header_size < 12 or header_size > len(decoded) or header_size % 4:
        raise ValueError(f"invalid decoded header size: {header_size}")

    words = [
        int.from_bytes(decoded[offset : offset + 4], "little")
        for offset in range(8, header_size, 4)
    ]
    if len(words) % 3:
        raise ValueError(
            f"decoded header has {len(words)} fields after magic/version; "
            "expected offset/size/count triplets"
        )

    triplets = []
    valid = True
    previous_end = header_size
    gaps = []
    for index in range(0, len(words), 3):
        offset, size, count = words[index : index + 3]
        in_range = (
            header_size <= offset <= len(decoded)
            and size <= len(decoded) - offset
        )
        if not in_range:
            valid = False
        if offset != previous_end:
            gaps.append(
                {
                    "triplet": index // 3,
                    "expected_offset": previous_end,
                    "actual_offset": offset,
                }
            )
        triplets.append(
            {
                "index": index // 3,
                "offset": offset,
                "size": size,
                "count": count,
                "end": offset + size,
                "in_range": in_range,
            }
        )
        previous_end = offset + size

    return {
        "valid": valid,
        "header_size": header_size,
        "triplet_count": len(triplets),
        "gaps": gaps,
        "triplets": triplets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--key", type=lambda value: int(value, 0), default=0x66)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source = args.input.read_bytes()
    decoded = decode(source, args.key, args.version)
    report = validate_triplet_header(decoded)
    report.update(
        {
            "input": str(args.input),
            "output": str(args.output),
            "source_size": len(source),
            "xor_key": args.key,
            "metadata_version": args.version,
            "magic": decoded[:4].hex(),
        }
    )
    if not report["valid"]:
        raise ValueError("decoded metadata header contains out-of-range sections")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(decoded)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "output": str(args.output),
                "size": len(decoded),
                "metadata_version": args.version,
                "header_size": report["header_size"],
                "triplet_count": report["triplet_count"],
                "gaps": len(report["gaps"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
