"""Normalize JSON and Unity Addressables binary catalogs without guessing edges."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping


CATALOG_MAGIC = 0x0DE38942
CATALOG_VERSION = 2
UINT_MAX = 0xFFFFFFFF
UNICODE_FLAG = 0x80000000
DYNAMIC_STRING_FLAG = 0x40000000
OFFSET_MASK = 0x3FFFFFFF
KNOWN_PROVIDERS = {
    "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.BundledAssetProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.SceneProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.BinaryDataProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.TextDataProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.JsonAssetProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.AtlasSpriteProvider",
    "UnityEngine.ResourceManagement.ResourceProviders.ContentCatalogProvider",
    "CriWare.CriAddressables.CriAssetProvider",
    "CriWare.CriAddressables.CriAtomProvider",
    "CriWare.CriAddressables.CriManaProvider",
    "CriWare.Assets.CriResourceProvider",
}


class CatalogAdapterError(RuntimeError):
    """Raised when a catalog cannot be normalized safely."""


class UnsupportedCatalogVersion(CatalogAdapterError):
    """Raised when a binary catalog schema is not supported."""


@dataclass(frozen=True)
class CatalogLocation:
    primary_key: str
    internal_id: str
    provider_id: str
    resource_type: str
    dependencies: tuple[str, ...]
    labels: tuple[str, ...]
    keys: tuple[str, ...]
    expected_hash: str | None
    expected_size: int | None
    expected_hash_algorithm: str | None = None
    unknown_fields: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogSnapshot:
    catalog_hash: str
    locations: tuple[CatalogLocation, ...]
    warnings: tuple[str, ...] = ()
    unknown_fields: Mapping[str, Any] = field(default_factory=dict)

    def location_for_key(self, key: str) -> CatalogLocation:
        for location in self.locations:
            if key == location.primary_key or key in location.keys or key in location.labels:
                return location
        raise KeyError(key)

    def locations_for_selector(self, selector: str) -> tuple[CatalogLocation, ...]:
        return tuple(
            location
            for location in self.locations
            if selector == location.primary_key
            or selector in location.keys
            or selector in location.labels
        )


class CatalogAdapter:
    def parse(self, path: Path) -> CatalogSnapshot:
        return self.parse_bytes(path.read_bytes(), source_name=str(path))

    def parse_bytes(self, data: bytes, *, source_name: str = "<memory>") -> CatalogSnapshot:
        stripped = data.lstrip()
        if stripped.startswith((b"{", b"[")):
            return self._parse_json(data, source_name)
        return _BinaryCatalogV2(data, source_name).parse()

    @staticmethod
    def _parse_json(data: bytes, source_name: str) -> CatalogSnapshot:
        try:
            document = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CatalogAdapterError(f"invalid JSON catalog: {source_name}") from error
        if not isinstance(document, dict) or not isinstance(document.get("locations"), list):
            raise CatalogAdapterError("JSON catalog must contain a locations array")

        known_catalog = {"catalogHash", "locations", "warnings"}
        unknown_catalog = {key: value for key, value in document.items() if key not in known_catalog}
        warnings = [str(value) for value in document.get("warnings", [])]
        merged: dict[tuple[str, str, str], CatalogLocation] = {}
        known_location = {
            "primaryKey", "internalId", "providerId", "resourceType", "dependencies",
            "labels", "keys", "expectedHash", "expectedSize", "expectedHashAlgorithm",
            "warnings",
        }
        for index, raw in enumerate(document["locations"]):
            if not isinstance(raw, dict):
                raise CatalogAdapterError(f"location {index} must be an object")
            try:
                internal_id = _required_string(raw, "internalId")
                provider_id = _required_string(raw, "providerId")
                resource_type = _required_string(raw, "resourceType")
            except (KeyError, TypeError, ValueError) as error:
                raise CatalogAdapterError(f"invalid location {index}: {error}") from error
            keys = _strings(raw.get("keys", ()), f"location {index} keys")
            primary_key = str(raw.get("primaryKey") or (keys[0] if keys else internal_id))
            expected_size = raw.get("expectedSize")
            if expected_size is not None and (type(expected_size) is not int or expected_size < 0):
                raise CatalogAdapterError(f"location {index} expectedSize must be non-negative")
            location = CatalogLocation(
                primary_key=primary_key,
                internal_id=internal_id,
                provider_id=provider_id,
                resource_type=resource_type,
                dependencies=_strings(raw.get("dependencies", ()), f"location {index} dependencies"),
                labels=_strings(raw.get("labels", ()), f"location {index} labels"),
                keys=keys,
                expected_hash=_optional_string(raw.get("expectedHash")),
                expected_size=expected_size,
                expected_hash_algorithm=_optional_string(raw.get("expectedHashAlgorithm"))
                or ("sha256" if _looks_like_sha256(raw.get("expectedHash")) else None),
                unknown_fields={key: value for key, value in raw.items() if key not in known_location},
                warnings=tuple(str(value) for value in raw.get("warnings", ())),
            )
            identity = (internal_id, provider_id, resource_type)
            previous = merged.get(identity)
            if previous is None:
                merged[identity] = location
            else:
                warnings.append(f"duplicate location merged: {internal_id}")
                merged[identity] = _merge_locations(previous, location)
            if provider_id not in KNOWN_PROVIDERS:
                warnings.append(f"unknown provider preserved: {provider_id}")

        raw_hash = document.get("catalogHash")
        catalog_hash = str(raw_hash) if raw_hash else hashlib.sha256(data).hexdigest()
        return CatalogSnapshot(
            catalog_hash=catalog_hash,
            locations=tuple(merged.values()),
            warnings=tuple(dict.fromkeys(warnings)),
            unknown_fields=unknown_catalog,
        )


def catalog_snapshot_to_dict(snapshot: CatalogSnapshot) -> dict[str, Any]:
    """Return the stable JSON projection consumed by later pipeline stages."""
    return {
        "catalogHash": snapshot.catalog_hash,
        "locations": [
            {
                "primaryKey": location.primary_key,
                "internalId": location.internal_id,
                "providerId": location.provider_id,
                "resourceType": location.resource_type,
                "dependencies": list(location.dependencies),
                "labels": list(location.labels),
                "keys": list(location.keys),
                "expectedHash": location.expected_hash,
                "expectedSize": location.expected_size,
                "expectedHashAlgorithm": location.expected_hash_algorithm,
                "unknownFields": dict(location.unknown_fields),
                "warnings": list(location.warnings),
            }
            for location in snapshot.locations
        ],
        "unknownFields": dict(snapshot.unknown_fields),
        "warnings": list(snapshot.warnings),
    }


class _BinaryCatalogV2:
    """Reader for Addressables ContentCatalogData binary schema version 2."""

    def __init__(self, data: bytes, source_name: str):
        self.data = data
        self.source_name = source_name

    def parse(self) -> CatalogSnapshot:
        if len(self.data) < 8:
            raise CatalogAdapterError(f"binary catalog is too small: {self.source_name}")
        magic, version = self._unpack("<ii", 0)
        if magic != CATALOG_MAGIC:
            raise CatalogAdapterError(f"invalid Addressables catalog magic: {self.source_name}")
        if version != CATALOG_VERSION:
            raise UnsupportedCatalogVersion(
                f"unsupported Addressables catalog version {version}; expected {CATALOG_VERSION}"
            )
        if len(self.data) < 32:
            raise CatalogAdapterError(f"binary catalog is too small: {self.source_name}")
        _, _, keys_offset, locator_id, *_ = self._unpack("<iiIIIIII", 0)

        key_rows = self._value_array(keys_offset, 8)
        aliases: dict[int, list[str]] = {}
        all_location_offsets: set[int] = set()
        for row in key_rows:
            key_object_offset, location_set_offset = struct.unpack_from("<II", row)
            key = self._read_untyped_object(key_object_offset)
            key_text = str(key)
            for location_offset in self._uint_array(location_set_offset):
                aliases.setdefault(location_offset, []).append(key_text)
                all_location_offsets.add(location_offset)

        raw_locations = {offset: self._read_location(offset) for offset in all_location_offsets}
        normalized: list[CatalogLocation] = []
        warnings = [
            "Addressables binary key kind is not encoded; label kind is not encoded and all aliases are preserved as selectors"
        ]
        identity_index: dict[tuple[str, str, str], int] = {}
        for offset in sorted(raw_locations):
            raw = raw_locations[offset]
            keys = tuple(dict.fromkeys(aliases.get(offset, ())))
            primary_key = raw["primary_key"]
            if primary_key not in keys:
                keys = (primary_key, *keys)
            dependency_keys = tuple(
                dict.fromkeys(raw_locations[dep]["primary_key"] for dep in raw["dependency_offsets"] if dep in raw_locations)
            )
            missing_deps = tuple(dep for dep in raw["dependency_offsets"] if dep not in raw_locations)
            location_warnings = []
            if missing_deps:
                location_warnings.append(f"unresolved dependency offsets: {missing_deps}")
            provider = raw["provider_id"]
            if provider not in KNOWN_PROVIDERS:
                warning = f"unknown provider preserved: {provider}"
                warnings.append(warning)
                location_warnings.append(warning)
            location = CatalogLocation(
                primary_key=primary_key,
                internal_id=raw["internal_id"],
                provider_id=provider,
                resource_type=raw["resource_type"],
                dependencies=dependency_keys,
                labels=tuple(key for key in keys if key != primary_key),
                keys=keys,
                expected_hash=raw["expected_hash"],
                expected_size=raw["expected_size"],
                expected_hash_algorithm=raw["expected_hash_algorithm"],
                unknown_fields=raw["unknown_fields"],
                warnings=tuple(location_warnings),
            )
            identity = (location.internal_id, location.provider_id, location.resource_type)
            if identity in identity_index:
                index = identity_index[identity]
                normalized[index] = _merge_locations(normalized[index], location)
                warnings.append(f"duplicate location merged: {location.internal_id}")
            else:
                identity_index[identity] = len(normalized)
                normalized.append(location)

        locator = None if locator_id == UINT_MAX else self._read_string(locator_id)
        return CatalogSnapshot(
            catalog_hash=hashlib.sha256(self.data).hexdigest(),
            locations=tuple(normalized),
            warnings=tuple(dict.fromkeys(warnings)),
            unknown_fields={"locatorId": locator, "binaryVersion": version},
        )

    def _read_location(self, offset: int) -> dict[str, Any]:
        (
            primary_key_offset,
            internal_id_offset,
            provider_offset,
            dependency_set_offset,
            dependency_hash,
            extra_data_offset,
            type_id,
        ) = self._unpack("<IIIIiII", offset)
        extra = self._read_untyped_object(extra_data_offset) if extra_data_offset != UINT_MAX else None
        expected_hash = None
        expected_size = None
        expected_algorithm = None
        unknown: dict[str, Any] = {"dependencyHashValue": dependency_hash}
        if isinstance(extra, dict) and extra.get("kind") == "AssetBundleRequestOptions":
            expected_hash = extra.get("hash")
            expected_size = extra.get("bundleSize")
            expected_algorithm = "unity-hash128"
            unknown["assetBundleOptions"] = extra
        elif extra is not None:
            unknown["extraData"] = extra
        return {
            "primary_key": self._read_string(primary_key_offset, "/"),
            "internal_id": self._read_string(internal_id_offset, "/"),
            "provider_id": self._read_string(provider_offset, "."),
            "dependency_offsets": self._uint_array(dependency_set_offset),
            "resource_type": self._read_type(type_id)[1],
            "expected_hash": expected_hash,
            "expected_size": expected_size,
            "expected_hash_algorithm": expected_algorithm,
            "unknown_fields": unknown,
        }

    def _read_untyped_object(self, offset: int) -> Any:
        if offset == UINT_MAX:
            return None
        type_id, object_id = self._unpack("<II", offset)
        _, class_name = self._read_type(type_id)
        if class_name == "System.String":
            string_id, separator_code = self._unpack("<IH", object_id)
            return self._read_string(string_id, chr(separator_code) if separator_code else "")
        if class_name == "System.Int32":
            return self._unpack("<i", object_id)[0]
        if class_name == "System.Int64":
            return self._unpack("<q", object_id)[0]
        if class_name == "System.Boolean":
            return bool(self._unpack("<?", object_id)[0])
        if class_name.endswith("AssetBundleRequestOptions"):
            hash_id, bundle_name_id, crc, bundle_size, common_id = self._unpack("<IIIII", object_id)
            common = self._unpack("<hBBi", common_id)
            return {
                "kind": "AssetBundleRequestOptions",
                "hash": self._hash128(hash_id),
                "bundleName": self._read_string(bundle_name_id, "_"),
                "crc": crc,
                "bundleSize": bundle_size,
                "timeout": common[0],
                "redirectLimit": common[1],
                "retryCount": common[2],
                "flags": common[3],
            }
        return {"serializedType": class_name, "objectOffset": object_id}

    def _read_type(self, offset: int) -> tuple[str, str]:
        if offset == UINT_MAX:
            return ("", "System.Object")
        assembly_id, class_id = self._unpack("<II", offset)
        return self._read_string(assembly_id, "."), self._read_string(class_id, ".")

    def _hash128(self, offset: int) -> str | None:
        if offset == UINT_MAX:
            return None
        values = self._unpack("<IIII", offset)
        return "".join(f"{value:08x}" for value in values)

    def _uint_array(self, offset: int) -> tuple[int, ...]:
        if offset == UINT_MAX:
            return ()
        payload = self._value_array_bytes(offset)
        if len(payload) % 4:
            raise CatalogAdapterError(f"truncated uint array at offset {offset}")
        return struct.unpack(f"<{len(payload) // 4}I", payload) if payload else ()

    def _value_array(self, offset: int, item_size: int) -> tuple[memoryview, ...]:
        payload = self._value_array_bytes(offset)
        if len(payload) % item_size:
            raise CatalogAdapterError(f"truncated value array at offset {offset}")
        view = memoryview(payload)
        return tuple(view[index:index + item_size] for index in range(0, len(payload), item_size))

    def _value_array_bytes(self, offset: int) -> bytes:
        if offset == UINT_MAX:
            return b""
        if offset < 4:
            raise CatalogAdapterError(f"invalid size-prefixed offset {offset}")
        size = self._unpack("<I", offset - 4)[0]
        self._check(offset, size)
        return self.data[offset:offset + size]

    def _read_string(self, string_id: int, separator: str = "") -> str:
        if string_id == UINT_MAX:
            return ""
        if separator and string_id & DYNAMIC_STRING_FLAG:
            parts: list[str] = []
            next_id = string_id
            seen: set[int] = set()
            while next_id != UINT_MAX:
                offset = next_id & OFFSET_MASK
                if offset in seen:
                    raise CatalogAdapterError(f"dynamic string cycle at offset {offset}")
                seen.add(offset)
                part_id, next_id = self._unpack("<II", offset)
                parts.append(self._read_string(part_id))
            return separator.join(reversed(parts))
        offset = string_id & OFFSET_MASK
        if offset < 4:
            raise CatalogAdapterError(f"invalid string offset {offset}")
        size = self._unpack("<I", offset - 4)[0]
        self._check(offset, size)
        encoding = "utf-16-le" if string_id & UNICODE_FLAG else "ascii"
        try:
            return self.data[offset:offset + size].decode(encoding)
        except UnicodeDecodeError as error:
            raise CatalogAdapterError(f"invalid {encoding} string at offset {offset}") from error

    def _unpack(self, pattern: str, offset: int) -> tuple[Any, ...]:
        size = struct.calcsize(pattern)
        self._check(offset, size)
        return struct.unpack_from(pattern, self.data, offset)

    def _check(self, offset: int, size: int) -> None:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise CatalogAdapterError(
                f"catalog offset out of bounds: offset={offset}, size={size}, length={len(self.data)}"
            )


def _required_string(raw: Mapping[str, Any], name: str) -> str:
    value = raw[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional string field must be non-empty when present")
    return value


def _strings(values: Iterable[Any], context: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise CatalogAdapterError(f"{context} must be an array")
    result = tuple(str(value) for value in values)
    if any(not value for value in result):
        raise CatalogAdapterError(f"{context} cannot contain empty values")
    return tuple(dict.fromkeys(result))


def _looks_like_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _merge_locations(first: CatalogLocation, second: CatalogLocation) -> CatalogLocation:
    expected_hash = first.expected_hash or second.expected_hash
    expected_size = first.expected_size if first.expected_size is not None else second.expected_size
    warnings = list(first.warnings) + list(second.warnings)
    if first.expected_hash and second.expected_hash and first.expected_hash != second.expected_hash:
        warnings.append("conflicting expected hashes preserved from first location")
    if first.expected_size is not None and second.expected_size is not None and first.expected_size != second.expected_size:
        warnings.append("conflicting expected sizes preserved from first location")
    return replace(
        first,
        dependencies=tuple(dict.fromkeys((*first.dependencies, *second.dependencies))),
        labels=tuple(dict.fromkeys((*first.labels, *second.labels))),
        keys=tuple(dict.fromkeys((*first.keys, *second.keys))),
        expected_hash=expected_hash,
        expected_size=expected_size,
        expected_hash_algorithm=first.expected_hash_algorithm or second.expected_hash_algorithm,
        unknown_fields={**second.unknown_fields, **first.unknown_fields},
        warnings=tuple(dict.fromkeys(warnings)),
    )
