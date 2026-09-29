#!/usr/bin/env python3
"""Inspect this game's restored IL2CPP metadata and map methods to native code."""

from __future__ import annotations

import argparse
import bisect
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR.parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from elftools.elf.elffile import ELFFile
except ImportError as error:
    raise SystemExit(
        "pyelftools is required. Install analysis dependencies with:\n"
        "python3 -m pip install --target analysis/vendor "
        "-r analysis/requirements.txt"
    ) from error


@dataclass(frozen=True)
class Image:
    name: str
    type_start: int
    type_count: int


@dataclass(frozen=True)
class Method:
    index: int
    name: str
    declaring_type: int
    token: int
    parameter_count: int


class MetadataV39:
    METHOD_RECORD_SIZE = 32
    TYPE_RECORD_SIZE = 82
    IMAGE_RECORD_SIZE = 36

    def __init__(self, path: Path):
        self.data = path.read_bytes()
        magic, version = struct.unpack_from("<II", self.data)
        if magic != 0xFAB11BAF or version != 39:
            raise ValueError(f"expected IL2CPP metadata v39, got {magic:#x} v{version}")

        self.sections = [
            struct.unpack_from("<III", self.data, 8 + index * 12)
            for index in range(31)
        ]
        self.string_offset = self.sections[2][0]
        self.method_offset, method_size, self.method_count = self.sections[5]
        self.type_offset, type_size, self.type_count = self.sections[19]
        self.image_offset, image_size, self.image_count = self.sections[20]

        self._require_record_size(
            "method", method_size, self.method_count, self.METHOD_RECORD_SIZE
        )
        self._require_record_size(
            "type", type_size, self.type_count, self.TYPE_RECORD_SIZE
        )
        self._require_record_size(
            "image", image_size, self.image_count, self.IMAGE_RECORD_SIZE
        )
        self.images = self._read_images()

    @staticmethod
    def _require_record_size(
        label: str, section_size: int, count: int, expected: int
    ) -> None:
        if count == 0 or section_size // count != expected:
            raise ValueError(
                f"unexpected {label} record size: {section_size}/{count}, "
                f"expected {expected}"
            )

    def string(self, index: int) -> str:
        start = self.string_offset + index
        end = self.data.index(0, start)
        return self.data[start:end].decode("utf-8", errors="replace")

    def _read_images(self) -> list[Image]:
        images = []
        for index in range(self.image_count):
            offset = self.image_offset + index * self.IMAGE_RECORD_SIZE
            name_index = struct.unpack_from("<I", self.data, offset)[0]
            type_start, type_count = struct.unpack_from("<HH", self.data, offset + 8)
            images.append(Image(self.string(name_index), type_start, type_count))
        return images

    def type_name(self, index: int) -> str:
        offset = self.type_offset + index * self.TYPE_RECORD_SIZE
        name_index, namespace_index = struct.unpack_from("<II", self.data, offset)
        name = self.string(name_index)
        namespace = self.string(namespace_index)
        return f"{namespace}.{name}" if namespace else name

    def image_for_type(self, type_index: int) -> Image:
        for image in self.images:
            if image.type_start <= type_index < image.type_start + image.type_count:
                return image
        raise KeyError(f"no image owns type index {type_index}")

    def methods(self) -> list[Method]:
        methods = []
        for index in range(self.method_count):
            offset = self.method_offset + index * self.METHOD_RECORD_SIZE
            name_index = struct.unpack_from("<I", self.data, offset)[0]
            declaring_type = struct.unpack_from("<H", self.data, offset + 4)[0]
            token = struct.unpack_from("<I", self.data, offset + 20)[0]
            parameter_count = struct.unpack_from("<H", self.data, offset + 30)[0]
            methods.append(
                Method(
                    index,
                    self.string(name_index),
                    declaring_type,
                    token,
                    parameter_count,
                )
            )
        return methods


class ElfMemory:
    R_AARCH64_RELATIVE = 1027

    def __init__(self, path: Path):
        self.stream = path.open("rb")
        self.elf = ELFFile(self.stream)
        self.segments = [
            segment.header
            for segment in self.elf.iter_segments()
            if segment.header.p_type == "PT_LOAD"
        ]
        self.relative_relocations: dict[int, int] = {}
        for section in self.elf.iter_sections():
            if section.header.sh_type != "SHT_RELA":
                continue
            for relocation in section.iter_relocations():
                if relocation["r_info_type"] == self.R_AARCH64_RELATIVE:
                    self.relative_relocations[relocation["r_offset"]] = relocation[
                        "r_addend"
                    ]

    def close(self) -> None:
        self.stream.close()

    def _file_offset(self, address: int) -> int:
        for segment in self.segments:
            start = segment.p_vaddr
            if start <= address < start + segment.p_filesz:
                return segment.p_offset + address - start
        raise ValueError(f"address is not file-backed: {address:#x}")

    def read(self, address: int, size: int) -> bytes:
        self.stream.seek(self._file_offset(address))
        data = self.stream.read(size)
        if len(data) != size:
            raise EOFError(f"short read at {address:#x}")
        return data

    def executable_ranges(self) -> list[tuple[int, bytes]]:
        ranges = []
        for segment in self.segments:
            if segment.p_flags & 1:
                ranges.append(
                    (segment.p_vaddr, self.read(segment.p_vaddr, segment.p_filesz))
                )
        return ranges

    def u64(self, address: int) -> int:
        if address in self.relative_relocations:
            return self.relative_relocations[address]
        return struct.unpack("<Q", self.read(address, 8))[0]

    def cstring(self, address: int) -> str:
        result = bytearray()
        while True:
            chunk = self.read(address + len(result), 256)
            end = chunk.find(0)
            if end >= 0:
                result.extend(chunk[:end])
                return result.decode("utf-8", errors="replace")
            result.extend(chunk)


@dataclass(frozen=True)
class CodeGenModule:
    name: str
    method_count: int
    method_pointers: int


def read_codegen_modules(memory: ElfMemory, code_registration: int) -> dict[str, CodeGenModule]:
    module_count = memory.u64(code_registration + 0x78)
    module_pointers = memory.u64(code_registration + 0x80)
    if not 0 < module_count < 10_000:
        raise ValueError(f"invalid CodeGen module count: {module_count}")

    modules = {}
    for index in range(module_count):
        module_address = memory.u64(module_pointers + index * 8)
        name = memory.cstring(memory.u64(module_address))
        modules[name] = CodeGenModule(
            name=name,
            method_count=memory.u64(module_address + 8),
            method_pointers=memory.u64(module_address + 16),
        )
    return modules


def method_address(
    memory: ElfMemory, modules: dict[str, CodeGenModule], image: Image, token: int
) -> int:
    module = modules.get(image.name)
    if module is None:
        # Stripped Unity images can remain in metadata without a CodeGen module.
        return 0
    row = token & 0x00FFFFFF
    if row == 0 or row > module.method_count:
        raise ValueError(
            f"method token {token:#010x} is outside {image.name} "
            f"pointer table ({module.method_count})"
        )
    try:
        return memory.u64(module.method_pointers + (row - 1) * 8)
    except ValueError:
        # A few Unity modules expose runtime-populated tables in BSS.
        return 0


@dataclass(frozen=True)
class MappedMethod:
    address: int
    image: str
    method: Method
    full_name: str


@dataclass(frozen=True)
class StructuredMethod:
    assembly: str
    type_name: str
    method_name: str
    parameter_count: int
    token: int
    native_address: Optional[int]

    def to_dict(self) -> dict[str, object]:
        return {
            "address": self.native_address,
            "assembly": self.assembly,
            "methodName": self.method_name,
            "parameterCount": self.parameter_count,
            "token": self.token,
            "typeName": self.type_name,
        }


def mapped_methods(
    metadata: MetadataV39,
    memory: ElfMemory,
    modules: dict[str, CodeGenModule],
) -> list[MappedMethod]:
    mapped = []
    type_names: dict[int, str] = {}
    for method in metadata.methods():
        image = metadata.image_for_type(method.declaring_type)
        address = method_address(memory, modules, image, method.token)
        if not address:
            continue
        type_name = type_names.setdefault(
            method.declaring_type, metadata.type_name(method.declaring_type)
        )
        mapped.append(
            MappedMethod(
                address,
                image.name,
                method,
                f"{type_name}.{method.name}",
            )
        )
    return mapped


def structured_methods(
    metadata: MetadataV39,
    memory: ElfMemory,
    modules: dict[str, CodeGenModule],
    *,
    included_types: set[str] | None = None,
) -> list[StructuredMethod]:
    """Return reusable method records, including metadata-only methods."""

    result = []
    type_names: dict[int, str] = {}
    for method in metadata.methods():
        type_name = type_names.setdefault(
            method.declaring_type,
            metadata.type_name(method.declaring_type),
        )
        if included_types is not None and type_name not in included_types:
            continue
        image = metadata.image_for_type(method.declaring_type)
        address = method_address(memory, modules, image, method.token)
        result.append(
            StructuredMethod(
                assembly=image.name,
                type_name=type_name,
                method_name=method.name,
                parameter_count=method.parameter_count,
                token=method.token,
                native_address=address or None,
            )
        )
    return result


def inspect_method_structures(
    metadata_path: Path,
    binary_path: Path,
    code_registration: int,
    *,
    included_types: set[str] | None = None,
) -> list[StructuredMethod]:
    """Inspect one client through a structured interface instead of stdout."""

    metadata = MetadataV39(metadata_path)
    memory = ElfMemory(binary_path)
    try:
        modules = read_codegen_modules(memory, code_registration)
        return structured_methods(
            metadata,
            memory,
            modules,
            included_types=included_types,
        )
    finally:
        memory.close()


def print_method(mapped: MappedMethod) -> None:
    print(
        f"{mapped.image}\t{mapped.method.token:#010x}\t{mapped.address:#x}\t"
        f"{mapped.method.parameter_count}\t{mapped.full_name}"
    )


def branch_target(address: int, instruction: int) -> Optional[tuple[str, int]]:
    opcode = instruction & 0xFC000000
    if opcode not in (0x14000000, 0x94000000):
        return None
    immediate = instruction & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 0x04000000
    kind = "BL" if opcode == 0x94000000 else "B"
    return kind, address + immediate * 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--code-registration", type=lambda value: int(value, 0), required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--search", help="case-insensitive method-name regex")
    operation.add_argument("--address", type=lambda value: int(value, 0))
    operation.add_argument("--xrefs-to", type=lambda value: int(value, 0))
    args = parser.parse_args()

    metadata = MetadataV39(args.metadata)
    memory = ElfMemory(args.binary)
    try:
        modules = read_codegen_modules(memory, args.code_registration)
        mapped = mapped_methods(metadata, memory, modules)
        matches = 0

        if args.search:
            pattern = re.compile(args.search, re.IGNORECASE)
            for candidate in mapped:
                if pattern.search(candidate.full_name):
                    print_method(candidate)
                    matches += 1
        elif args.address is not None:
            for candidate in mapped:
                if candidate.address == args.address:
                    print_method(candidate)
                    matches += 1
        else:
            by_address = sorted(mapped, key=lambda candidate: candidate.address)
            starts = [candidate.address for candidate in by_address]
            seen = set()
            for range_address, data in memory.executable_ranges():
                for offset in range(0, len(data) - 3, 4):
                    instruction = struct.unpack_from("<I", data, offset)[0]
                    branch = branch_target(range_address + offset, instruction)
                    if branch is None or branch[1] != args.xrefs_to:
                        continue
                    call_address = range_address + offset
                    owner_index = bisect.bisect_right(starts, call_address) - 1
                    if owner_index < 0:
                        continue
                    owner = by_address[owner_index]
                    key = (call_address, owner.address, branch[0])
                    if key in seen:
                        continue
                    seen.add(key)
                    print(
                        f"{branch[0]}\t{call_address:#x}\t{owner.address:#x}\t"
                        f"{owner.image}\t{owner.method.token:#010x}\t"
                        f"{owner.full_name}"
                    )
                    matches += 1
        return 0 if matches else 1
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
