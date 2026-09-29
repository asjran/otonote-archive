"""Deterministic, offline-only Android split package intake."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

from .client_profile import CRITICAL_TYPE_ADAPTERS, ClientProfile, ClientProfileBuilder, MethodStructure


class PackageIntakeError(RuntimeError):
    pass


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_apksigner_output(text: str) -> str:
    for line in text.splitlines():
        if "certificate SHA-256 digest:" in line:
            value = line.rsplit(":", 1)[1].strip().lower().replace(":", "")
            if len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
                return value
    raise PackageIntakeError("apksigner output has no certificate SHA-256 digest")


def _lp32(blob: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(blob):
        raise PackageIntakeError("truncated APK signing block")
    size = struct.unpack_from("<I", blob, offset)[0]
    start = offset + 4
    end = start + size
    if end > len(blob):
        raise PackageIntakeError("truncated APK signing value")
    return blob[start:end], end


def certificate_sha256_from_apk(path: Path) -> str:
    """Extract the first v2/v3 signer certificate without executing Android tools."""
    data = path.read_bytes()
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if eocd < 0:
        raise PackageIntakeError(f"{path.name}: ZIP end record missing")
    central = struct.unpack_from("<I", data, eocd + 16)[0]
    if central < 24 or data[central - 16:central] != b"APK Sig Block 42":
        raise PackageIntakeError(f"{path.name}: APK signing block missing")
    size = struct.unpack_from("<Q", data, central - 24)[0]
    start = central - size - 8
    if start < 0 or struct.unpack_from("<Q", data, start)[0] != size:
        raise PackageIntakeError(f"{path.name}: invalid APK signing block")
    cursor = start + 8
    pairs_end = central - 24
    values: dict[int, bytes] = {}
    while cursor < pairs_end:
        pair_size = struct.unpack_from("<Q", data, cursor)[0]
        pair_start = cursor + 8
        pair_end = pair_start + pair_size
        if pair_size < 4 or pair_end > pairs_end:
            raise PackageIntakeError(f"{path.name}: invalid APK signer pair")
        pair_id = struct.unpack_from("<I", data, pair_start)[0]
        values[pair_id] = data[pair_start + 4:pair_end]
        cursor = pair_end
    for scheme_id in (0x7109871A, 0xF05368C0, 0x1B93AD61):
        value = values.get(scheme_id)
        if value is None:
            continue
        signers, _ = _lp32(value, 0)
        signer, _ = _lp32(signers, 0)
        signed_data, _ = _lp32(signer, 0)
        _, pos = _lp32(signed_data, 0)  # digests
        certificates, _ = _lp32(signed_data, pos)
        certificate, _ = _lp32(certificates, 0)
        return hashlib.sha256(certificate).hexdigest()
    raise PackageIntakeError(f"{path.name}: APK v2/v3 signer missing")


def inspect_apk(path: Path) -> dict[str, Any]:
    try:
        from analysis.parse_ournotes_apk import parse_axml
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "AndroidManifest.xml"
            manifest_path.write_bytes(archive.read("AndroidManifest.xml"))
            manifest = parse_axml(manifest_path).get("manifest", {})
    except Exception as exc:
        raise PackageIntakeError(f"cannot inspect {path.name}") from exc
    try:
        return {
            "packageName": str(manifest["package"]),
            "versionName": manifest.get("android:versionName"),
            "versionCode": int(manifest["android:versionCode"]),
            "splitName": manifest.get("split"),
            "certificateSha256": certificate_sha256_from_apk(path),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise PackageIntakeError(f"{path.name}: incomplete package identity") from exc


def build_package_set_manifest(
    apk_root: Path,
    *,
    region: str,
    channel: str,
    inspector: Callable[[Path], dict[str, Any]] = inspect_apk,
) -> dict[str, Any]:
    paths = sorted(apk_root.glob("*.apk"), key=lambda path: path.name)
    if not paths:
        raise PackageIntakeError("package set contains no APKs")
    inspected = [(path, inspector(path)) for path in paths]
    bases = [(path, facts) for path, facts in inspected if facts.get("splitName") in (None, "")]
    if len(bases) != 1:
        raise PackageIntakeError("package set must contain exactly one base APK")
    base = bases[0][1]
    split_names = [facts.get("splitName") or "base" for _, facts in inspected]
    if len(set(split_names)) != len(split_names):
        raise PackageIntakeError("package set contains duplicate split names")
    if "UnityDataAssetPack" not in split_names:
        raise PackageIntakeError("package set is missing UnityDataAssetPack Asset Pack")
    if "config.arm64_v8a" not in split_names:
        raise PackageIntakeError("package set is missing arm64 native split")
    for path, facts in inspected:
        for key in ("packageName", "versionCode", "certificateSha256"):
            if facts.get(key) != base.get(key):
                raise PackageIntakeError(f"{path.name}: inconsistent {key}")
        candidate_version = facts.get("versionName")
        if candidate_version not in (None, "", base.get("versionName")):
            raise PackageIntakeError(f"{path.name}: inconsistent versionName")
    splits = []
    for path, facts in inspected:
        logical_name = facts.get("splitName") or "base"
        splits.append({
            "logicalName": logical_name,
            "splitName": facts.get("splitName"),
            "sha256": _sha256(path),
            "byteSize": path.stat().st_size,
            "certificateSha256": facts["certificateSha256"],
        })
    splits.sort(key=lambda item: (item["logicalName"] != "base", item["logicalName"]))
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "identity": {"region": region, "channel": channel},
        "packageName": base["packageName"],
        "versionName": base["versionName"],
        "versionCode": base["versionCode"],
        "certificateSha256": base["certificateSha256"],
        "splits": splits,
    }
    manifest["packageSetSha256"] = _canonical_sha(manifest)
    return manifest


def read_methods_tsv(path: Path) -> list[dict[str, Any]]:
    """Read only structural IL2CPP fields; native addresses are discarded."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as stream:
        rows = csv.reader(stream, delimiter="\t")
        for row in rows:
            if len(row) < 7 or row[0].startswith("#"):
                continue
            try:
                token = int(row[4], 0)
                parameter_count = int(row[5], 0)
            except ValueError:
                continue
            records.append({"assembly": row[1], "typeName": row[2], "methodName": row[3], "token": token, "parameterCount": parameter_count})
    return records


def build_client_profile(
    package_set: dict[str, Any],
    *,
    methods_path: Path,
    metadata_version: int,
    abi: str,
    unity_version: str = "6000.3.12f1",
) -> ClientProfile:
    methods = [MethodStructure.from_mapping(item) for item in read_methods_tsv(methods_path)]
    profile = ClientProfileBuilder(
        package_name=package_set["packageName"],
        package_signature_sha256=package_set["certificateSha256"],
        unity_version=unity_version,
        metadata_version=metadata_version,
        abi=abi,
    ).build(methods=methods, sensitive_constants={})
    return ClientProfile(
        package_name=profile.package_name,
        package_signature_sha256=profile.package_signature_sha256,
        unity_version=profile.unity_version,
        metadata_version=profile.metadata_version,
        abi=profile.abi,
        methods=profile.methods,
        constant_hashes=profile.constant_hashes,
        protocol_services=profile.protocol_services,
        structure_fingerprint=profile.structure_fingerprint,
        analysis_status=("supported" if set(CRITICAL_TYPE_ADAPTERS) <= {item.type_name for item in profile.methods} else "review_required"),
        package_set_sha256=package_set["packageSetSha256"],
    )


def aggregate_asset_manifests(bundle_root: Path, *, catalog_sha256: str) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for path in sorted(bundle_root.glob("*/manifest.json"), key=lambda item: item.parent.name):
        value = json.loads(path.read_text(encoding="utf-8"))
        bundle = path.parent.name
        objects = value.get("objects", [])
        if not isinstance(objects, list):
            unknown.append({"bundle": bundle, "reason": "source_missing", "fingerprint": _canonical_sha(value)})
            continue
        for index, item in enumerate(objects):
            if not isinstance(item, dict):
                unknown.append({"bundle": bundle, "index": index, "reason": "source_missing", "fingerprint": _canonical_sha(item)})
                continue
            exported = item.get("exported_file")
            relative_export = f"{bundle}/{exported}" if isinstance(exported, str) and exported else None
            path_id = item.get("path_id")
            assets.append({
                "bundle": bundle,
                "path_id": path_id,
                "type": item.get("type"),
                "name": item.get("name"),
                "exported_file": relative_export,
                "path": relative_export or f"{bundle}/{item.get('type')}/{index}",
                "byteSize": (
                    (bundle_root / relative_export).stat().st_size
                    if relative_export and (bundle_root / relative_export).is_file()
                    else None
                ),
            })
    assets.sort(key=lambda item: (item["bundle"], str(item["path_id"]), str(item["type"])))
    count = len(list(bundle_root.glob("*/manifest.json")))
    return {"schemaVersion": 1, "catalogSha256": catalog_sha256, "bundle_count": count, "assets": assets, "unknown": unknown, "sourceManifestCount": count}
