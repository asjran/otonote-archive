#!/usr/bin/env python3
"""Restore the page-wise XOR obfuscation used by this IL2CPP metadata file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


IL2CPP_MAGIC = bytes.fromhex("AF1BB1FA")


def decode(
    source: bytes,
    *,
    key: int,
    version: int,
    page_size: int,
    period_pages: int,
    xor_page_residues: set[int],
) -> tuple[bytes, list[int]]:
    decoded = bytearray(source)
    decoded_pages = []

    page_count = (len(source) + page_size - 1) // page_size
    for page_index in range(page_count):
        residue = page_index % period_pages
        if page_index != 0 and residue not in xor_page_residues:
            continue

        start = page_index * page_size
        end = min(start + page_size, len(source))
        decoded[start:end] = (value ^ key for value in source[start:end])
        decoded_pages.append(page_index)

    decoded[:4] = IL2CPP_MAGIC
    decoded[4:8] = version.to_bytes(4, "little")
    return bytes(decoded), decoded_pages


def read_sections(decoded: bytes) -> tuple[int, list[dict[str, int]]]:
    if len(decoded) < 12:
        raise ValueError("metadata file is too small")

    header_size = int.from_bytes(decoded[8:12], "little")
    if header_size < 12 or header_size > len(decoded) or header_size % 12 != 8:
        raise ValueError(f"invalid decoded header size: {header_size}")

    sections = []
    for offset in range(8, header_size, 12):
        section_offset = int.from_bytes(decoded[offset : offset + 4], "little")
        size = int.from_bytes(decoded[offset + 4 : offset + 8], "little")
        count = int.from_bytes(decoded[offset + 8 : offset + 12], "little")
        if section_offset < header_size or section_offset + size > len(decoded):
            raise ValueError(
                f"section {len(sections)} is outside the file: "
                f"offset={section_offset}, size={size}"
            )
        sections.append(
            {
                "index": len(sections),
                "offset": section_offset,
                "size": size,
                "count": count,
            }
        )

    return header_size, sections


def parse_residues(value: str) -> set[int]:
    residues = {int(item, 0) for item in value.split(",") if item.strip()}
    if not residues:
        raise argparse.ArgumentTypeError("at least one page residue is required")
    return residues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--key", type=lambda value: int(value, 0), default=0x66)
    parser.add_argument("--version", type=int, default=39)
    parser.add_argument("--page-size", type=int, default=4096)
    parser.add_argument("--period-pages", type=int, default=16)
    parser.add_argument(
        "--xor-page-residues",
        type=parse_residues,
        default={1, 2, 3, 4},
        help="comma-separated page residues; page zero is always decoded",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source = args.input.read_bytes()
    decoded, decoded_pages = decode(
        source,
        key=args.key,
        version=args.version,
        page_size=args.page_size,
        period_pages=args.period_pages,
        xor_page_residues=args.xor_page_residues,
    )
    header_size, sections = read_sections(decoded)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(decoded)

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "source_size": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(decoded).hexdigest(),
        "metadata_version": args.version,
        "xor_key": args.key,
        "page_size": args.page_size,
        "period_pages": args.period_pages,
        "xor_page_residues": sorted(args.xor_page_residues),
        "decoded_page_count": len(decoded_pages),
        "decoded_pages": decoded_pages,
        "header_size": header_size,
        "sections": sections,
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
                    "metadata_version",
                    "decoded_page_count",
                    "header_size",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
