#!/usr/bin/env python3
"""List direct IL2CPP method-to-method branches inside one native method."""

from __future__ import annotations

import argparse
import re
import struct
from collections import defaultdict
from pathlib import Path

from crypto.inspect_il2cpp import (
    ElfMemory,
    MetadataV39,
    branch_target,
    mapped_methods,
    read_codegen_modules,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--code-registration", type=lambda value: int(value, 0), required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--address", type=lambda value: int(value, 0))
    selector.add_argument("--search", help="case-insensitive full method-name regex")
    parser.add_argument("--max-bytes", type=lambda value: int(value, 0), default=0x8000)
    args = parser.parse_args()

    metadata = MetadataV39(args.metadata)
    memory = ElfMemory(args.binary)
    try:
        modules = read_codegen_modules(memory, args.code_registration)
        mapped = mapped_methods(metadata, memory, modules)
        by_address: dict[int, list[object]] = defaultdict(list)
        for method in mapped:
            by_address[method.address].append(method)
        starts = sorted(by_address)

        if args.address is not None:
            selected_starts = [start for start in starts if start == args.address]
        else:
            pattern = re.compile(args.search, re.IGNORECASE)
            selected_starts = sorted(
                {
                    method.address
                    for method in mapped
                    if pattern.search(method.full_name)
                }
            )

        if not selected_starts:
            raise SystemExit("no exact mapped method matched")

        start_index = {address: index for index, address in enumerate(starts)}
        for start in selected_starts:
            names = " | ".join(method.full_name for method in by_address[start])
            index = start_index[start]
            natural_end = starts[index + 1] if index + 1 < len(starts) else start + 4
            end = min(natural_end, start + args.max_bytes)
            print(f"METHOD\t{start:#x}\t{end:#x}\t{names}")
            data = memory.read(start, end - start)
            for offset in range(0, len(data) - 3, 4):
                instruction = struct.unpack_from("<I", data, offset)[0]
                target = branch_target(start + offset, instruction)
                if target is None:
                    continue
                kind, target_address = target
                callees = by_address.get(target_address)
                if not callees:
                    continue
                callee_names = " | ".join(method.full_name for method in callees)
                print(
                    f"{kind}\t{start + offset:#x}\t{target_address:#x}\t"
                    f"{callee_names}"
                )
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
