#!/usr/bin/env python3
"""Restore page-wise XOR obfuscation in a native binary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ELF_MAGIC = b"\x7fELF"


def parse_residues(value: str) -> set[int]:
    residues = {int(item, 0) for item in value.split(",") if item.strip()}
    if not residues:
        raise argparse.ArgumentTypeError("at least one page residue is required")
    return residues


def decode(
    source: bytes,
    *,
    key: int,
    page_size: int,
    period_pages: int,
    xor_page_residues: set[int],
    start_offset: int,
    end_offset: int,
) -> tuple[bytes, list[int]]:
    decoded = bytearray(source)
    decoded_pages = []

    page_count = (len(source) + page_size - 1) // page_size
    for page_index in range(page_count):
        if page_index % period_pages not in xor_page_residues:
            continue

        start = page_index * page_size
        end = min(start + page_size, len(source))
        start = max(start, start_offset)
        end = min(end, end_offset)
        if start >= end:
            continue
        decoded[start:end] = (value ^ key for value in source[start:end])
        decoded_pages.append(page_index)

    return bytes(decoded), decoded_pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--key", type=lambda value: int(value, 0), default=0x39)
    parser.add_argument("--page-size", type=int, default=4096)
    parser.add_argument("--period-pages", type=int, default=16)
    parser.add_argument(
        "--xor-page-residues",
        type=parse_residues,
        default={11, 12, 13, 14},
        help="comma-separated page residues",
    )
    parser.add_argument("--start-offset", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--end-offset", type=lambda value: int(value, 0))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source = args.input.read_bytes()
    end_offset = len(source) if args.end_offset is None else args.end_offset
    if not 0 <= args.start_offset <= end_offset <= len(source):
        raise ValueError("decode offset range is outside the input")
    decoded, decoded_pages = decode(
        source,
        key=args.key,
        page_size=args.page_size,
        period_pages=args.period_pages,
        xor_page_residues=args.xor_page_residues,
        start_offset=args.start_offset,
        end_offset=end_offset,
    )
    if source.startswith(ELF_MAGIC) and not decoded.startswith(ELF_MAGIC):
        raise ValueError("decoded output no longer has a valid ELF magic")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(decoded)

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "source_size": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(decoded).hexdigest(),
        "xor_key": args.key,
        "page_size": args.page_size,
        "period_pages": args.period_pages,
        "xor_page_residues": sorted(args.xor_page_residues),
        "start_offset": args.start_offset,
        "end_offset": end_offset,
        "decoded_page_count": len(decoded_pages),
        "decoded_pages": decoded_pages,
        "elf_magic_valid": decoded.startswith(ELF_MAGIC),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "output",
                    "source_size",
                    "output_sha256",
                    "decoded_page_count",
                    "elf_magic_valid",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
