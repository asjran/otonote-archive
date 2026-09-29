"""Offline registration and verification of a known-good content release."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Channel, ClientBuild, ContentRelease, Region, VersionVector
from .object_store import FileObjectStore
from .release_repository import ReleaseRepository


class GoldenError(RuntimeError):
    """Raised when a Golden baseline cannot be registered or verified."""


CURRENT_SITE_MASTER_TABLES = (
    "MasterBand",
    "MasterCharacter",
    "MasterLiveCharacter",
    "MasterLiveMusic",
    "MasterLiveMusicCategory",
    "MasterLiveMusicScore",
    "MasterTag",
    "MasterText",
)


@dataclass(frozen=True)
class GoldenInputs:
    apk: Path
    il2cpp: Path
    metadata: Path
    catalog: Path
    catalog_hash: Path
    master_version: Path
    master_root: Path
    asset_manifest: Path
    package_set_manifest: Path | None = None
    client_profile: Path | None = None


@dataclass(frozen=True)
class GoldenClientFacts:
    package_name: str
    version_name: str
    version_code: int
    unity_version: str
    metadata_version: int
    auth_profile_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "package_name",
            "version_name",
            "unity_version",
            "auth_profile_ref",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if type(self.version_code) is not int or self.version_code <= 0:
            raise ValueError("version_code must be a positive integer")
        if type(self.metadata_version) is not int or self.metadata_version <= 0:
            raise ValueError("metadata_version must be a positive integer")

    @property
    def client_generation(self) -> str:
        unity_major = self.unity_version.split(".", 1)[0]
        return f"unity{unity_major}-il2cpp{self.metadata_version}-v1"


@dataclass(frozen=True)
class GoldenRegistration:
    baseline_path: Path
    client_build_id: str
    content_release_id: str
    archived_object_count: int


@dataclass(frozen=True)
class GoldenVerification:
    client_build_id: str
    content_release_id: str
    verified_object_count: int


def inspect_apk_client_facts(
    apk: Path,
    *,
    metadata_version: int,
    auth_profile_ref: str,
) -> GoldenClientFacts:
    """Read stable client identity from the APK without executing it."""

    try:
        from analysis.parse_ournotes_apk import parse_axml, parse_unityfs_header
    except ImportError as exc:  # pragma: no cover - repository packaging failure
        raise GoldenError("APK analysis helpers are unavailable") from exc

    try:
        with zipfile.ZipFile(apk) as archive:
            with tempfile.TemporaryDirectory() as temporary:
                temporary_root = Path(temporary)
                manifest_path = temporary_root / "AndroidManifest.xml"
                unity_path = temporary_root / "data.unity3d"
                manifest_path.write_bytes(archive.read("AndroidManifest.xml"))
                unity_path.write_bytes(
                    archive.read("assets/bin/Data/data.unity3d")
                )
                manifest = parse_axml(manifest_path).get("manifest", {})
                unity = parse_unityfs_header(unity_path) or {}
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise GoldenError(f"cannot inspect APK client identity: {apk.name}") from exc

    try:
        package_name = manifest["package"]
        version_name = manifest["android:versionName"]
        version_code = int(manifest["android:versionCode"])
        unity_version = unity["unity_version"]
    except (KeyError, TypeError, ValueError) as exc:
        raise GoldenError("APK is missing required client identity fields") from exc
    return GoldenClientFacts(
        package_name=package_name,
        version_name=version_name,
        version_code=version_code,
        unity_version=unity_version,
        metadata_version=metadata_version,
        auth_profile_ref=auth_profile_ref,
    )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenError(f"cannot read {description}: {path.name}") from exc
    if not isinstance(value, dict):
        raise GoldenError(f"{description} must be a JSON object: {path.name}")
    return value


def _master_row_count(value: Any, name: str) -> int:
    if isinstance(value, dict) and "_allData" in value:
        value = value["_allData"]
    if isinstance(value, (list, dict)):
        return len(value)
    raise GoldenError(f"master table {name} has unsupported row storage")


def _master_aggregate(objects: Iterable[dict[str, Any]]) -> str:
    value = [
        {"logicalName": item["logicalName"], "sha256": item["sha256"]}
        for item in objects
    ]
    payload = json.dumps(
        sorted(value, key=lambda item: item["logicalName"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class GoldenRegistry:
    """Owns the complete Golden registration workflow behind two methods."""

    def __init__(self, *, data_root: Path, baseline_path: Path):
        self._store = FileObjectStore(data_root)
        self._releases = ReleaseRepository(data_root)
        self._baseline_path = baseline_path

    def register(
        self,
        *,
        region: Region,
        channel: Channel,
        inputs: GoldenInputs,
        client: GoldenClientFacts,
    ) -> GoldenRegistration:
        if not isinstance(region, Region) or not isinstance(channel, Channel):
            raise GoldenError("region and channel must be explicitly confirmed")
        self._validate_inputs(inputs)

        primary_paths = {
            "apk": inputs.apk,
            "il2cpp": inputs.il2cpp,
            "metadata": inputs.metadata,
            "catalog": inputs.catalog,
            "catalogHash": inputs.catalog_hash,
            "masterVersion": inputs.master_version,
            "assetManifest": inputs.asset_manifest,
        }
        object_records: list[dict[str, Any]] = []
        primary_summary: dict[str, dict[str, Any]] = {}
        for role, path in primary_paths.items():
            record = self._archive(path, role=role, logical_name=path.name)
            object_records.append(record)
            primary_summary[role] = {
                "sha256": record["sha256"],
                "byteSize": record["byteSize"],
                "sourceKind": role,
            }

        package_set: dict[str, Any] | None = None
        profile: dict[str, Any] | None = None
        if inputs.package_set_manifest is not None:
            package_set = _load_json_object(inputs.package_set_manifest, "package set manifest")
            if inputs.client_profile is None:
                raise GoldenError("split package registration requires a ClientProfile")
            profile = _load_json_object(inputs.client_profile, "ClientProfile")
            if profile.get("packageSetSha256") != package_set.get("packageSetSha256"):
                raise GoldenError("ClientProfile does not match package set")
            split_paths = {
                "base": inputs.apk,
                "UnityDataAssetPack": inputs.apk.parent / "split_UnityDataAssetPack.apk",
                "config.arm64_v8a": inputs.apk.parent / "split_config.arm64_v8a.apk",
            }
            for split in package_set.get("splits", []):
                logical = split.get("logicalName")
                path = split_paths.get(logical)
                if path is None or not path.is_file() or _sha256_path(path) != split.get("sha256"):
                    raise GoldenError(f"split object does not match package manifest: {logical}")
                if logical == "base":
                    continue
                record = self._archive(path, role=f"apkSplit:{logical}", logical_name=path.name)
                object_records.append(record)
                primary_summary[record["role"]] = {"sha256": record["sha256"], "byteSize": record["byteSize"], "sourceKind": record["role"]}

        master_records: list[dict[str, Any]] = []
        master_rows: dict[str, int] = {}
        for path in sorted(inputs.master_root.glob("*.json")):
            value = _load_json_object(path, "master table")
            table_name = path.stem
            master_rows[table_name] = _master_row_count(value, table_name)
            record = self._archive(
                path,
                role="masterTable",
                logical_name=path.name,
            )
            master_records.append(record)
            object_records.append(record)

        missing_tables = sorted(set(CURRENT_SITE_MASTER_TABLES) - master_rows.keys())
        if missing_tables:
            raise GoldenError(
                "Golden master is missing tables required by the current site: "
                + ", ".join(missing_tables)
            )

        asset_manifest = _load_json_object(inputs.asset_manifest, "asset manifest")
        statistics = self._statistics(master_rows, asset_manifest)
        catalog_version = self._read_version(inputs.catalog_hash, "catalog hash")
        master_version = self._read_version(inputs.master_version, "master version")

        client_build = ClientBuild(
            region=region,
            channel=channel,
            platform="android",
            package_name=client.package_name,
            version_name=client.version_name,
            version_code=client.version_code,
            package_sha256=(primary_summary["apk"]["sha256"] if package_set is None else package_set["packageSetSha256"]),
            unity_version=client.unity_version,
            client_generation=client.client_generation,
            auth_profile_ref=client.auth_profile_ref,
        )
        vector = VersionVector(
            client_version=f"{client.version_name}+{client.version_code}",
            minimum_client_version=None,
            bootstrap_revision=None,
            catalog_hash=catalog_version,
            master_version=master_version,
            asset_manifest_version=primary_summary["assetManifest"]["sha256"],
            remote_code_hash=None,
        )
        release = ContentRelease.for_client_build(client_build, vector)
        self._releases.create_candidate(
            release,
            {
                "baseline": True,
                "clientBuild": {
                    "id": client_build.id,
                    "packageName": client.package_name,
                    "versionName": client.version_name,
                    "versionCode": client.version_code,
                    "packageSha256": client_build.package_sha256,
                    "unityVersion": client.unity_version,
                    "metadataVersion": client.metadata_version,
                    "clientGeneration": client.client_generation,
                    "authProfileRef": client.auth_profile_ref,
                },
                "objects": object_records,
                "statistics": statistics,
                "clientProfileFingerprint": None if profile is None else profile.get("structureFingerprint"),
                "packageSetSha256": None if package_set is None else package_set.get("packageSetSha256"),
                "splits": [] if package_set is None else package_set.get("splits", []),
            },
        )

        baseline = {
            "schemaVersion": 1,
            "baselineId": self._baseline_path.stem,
            "identity": {
                "region": region.value,
                "channel": channel.value,
                "clientBuildId": client_build.id,
                "contentReleaseId": release.id,
            },
            "client": {
                "packageName": client.package_name,
                "versionName": client.version_name,
                "versionCode": client.version_code,
                "unityVersion": client.unity_version,
                "metadataVersion": client.metadata_version,
                "clientGeneration": client.client_generation,
            },
            "packageSetSha256": None if package_set is None else package_set.get("packageSetSha256"),
            "clientProfileFingerprint": None if profile is None else profile.get("structureFingerprint"),
            "versionVector": vector.as_canonical_dict(),
            "objects": primary_summary,
            "master": {
                "aggregateSha256": _master_aggregate(master_records),
            },
            "statistics": statistics,
        }
        self._write_baseline(baseline)
        return GoldenRegistration(
            baseline_path=self._baseline_path,
            client_build_id=client_build.id,
            content_release_id=release.id,
            archived_object_count=len(object_records),
        )

    def verify(self) -> GoldenVerification:
        baseline = _load_json_object(self._baseline_path, "Golden baseline")
        try:
            identity = baseline["identity"]
            region = Region(identity["region"])
            channel = Channel(identity["channel"])
            release_id = identity["contentReleaseId"]
            expected_build_id = identity["clientBuildId"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GoldenError("Golden baseline identity is invalid") from exc
        manifest = self._releases.load_manifest(region, channel, release_id)
        if (
            manifest.get("contentRelease", {}).get("observedByClientBuildRef")
            != expected_build_id
        ):
            raise GoldenError("Golden ClientBuild reference does not match release")
        if manifest.get("contentRelease", {}).get("versionVector") != baseline.get(
            "versionVector"
        ):
            raise GoldenError("Golden version vector does not match release")

        objects = manifest.get("objects")
        if not isinstance(objects, list) or not objects:
            raise GoldenError("Golden release does not reference any objects")
        master_records: list[dict[str, Any]] = []
        master_rows: dict[str, int] = {}
        asset_manifest: dict[str, Any] | None = None
        primary_summary: dict[str, dict[str, Any]] = {}
        for record in objects:
            self._verify_object(record)
            role = record.get("role")
            if role == "masterTable":
                master_records.append(record)
                with self._store.open_object(record["sha256"]) as stream:
                    value = json.load(stream)
                table_name = Path(record["logicalName"]).stem
                master_rows[table_name] = _master_row_count(value, table_name)
            elif role == "assetManifest":
                with self._store.open_object(record["sha256"]) as stream:
                    value = json.load(stream)
                if not isinstance(value, dict):
                    raise GoldenError("archived asset manifest is not an object")
                asset_manifest = value
                primary_summary[role] = {
                    "sha256": record["sha256"],
                    "byteSize": record["byteSize"],
                    "sourceKind": role,
                }
            else:
                primary_summary[role] = {
                    "sha256": record["sha256"],
                    "byteSize": record["byteSize"],
                    "sourceKind": role,
                }
        if asset_manifest is None:
            raise GoldenError("Golden release is missing its asset manifest")
        if primary_summary != baseline.get("objects"):
            raise GoldenError("Golden primary object summary changed")
        if _master_aggregate(master_records) != baseline.get("master", {}).get(
            "aggregateSha256"
        ):
            raise GoldenError("Golden master aggregate hash changed")
        actual_statistics = self._statistics(master_rows, asset_manifest)
        if actual_statistics != baseline.get("statistics"):
            raise GoldenError("Golden content statistics changed")
        return GoldenVerification(
            client_build_id=expected_build_id,
            content_release_id=release_id,
            verified_object_count=len(objects),
        )

    def _archive(self, path: Path, *, role: str, logical_name: str) -> dict[str, Any]:
        expected = _sha256_path(path)
        with path.open("rb") as stream:
            stored = self._store.put_stream(
                stream,
                job_id="register-golden",
                expected_sha256=expected,
            )
        return {
            "role": role,
            "logicalName": logical_name,
            "sha256": stored.sha256,
            "byteSize": stored.byte_size,
        }

    def _verify_object(self, record: Any) -> None:
        if not isinstance(record, dict):
            raise GoldenError("Golden object reference is invalid")
        try:
            role = record["role"]
            logical_name = record["logicalName"]
            sha256 = record["sha256"]
            byte_size = record["byteSize"]
        except KeyError as exc:
            raise GoldenError("Golden object reference is incomplete") from exc
        if not isinstance(role, str) or not role.strip():
            raise GoldenError("Golden object role is invalid")
        if (
            not isinstance(logical_name, str)
            or not logical_name.strip()
            or Path(logical_name).name != logical_name
        ):
            raise GoldenError("Golden object logical name is invalid")
        if not self._store.has_object(sha256):
            raise GoldenError(f"Golden object is missing: {sha256}")
        metadata = self._store.object_metadata(sha256)
        if metadata.byte_size != byte_size or _sha256_path(metadata.path) != sha256:
            raise GoldenError(f"Golden object failed integrity verification: {sha256}")

    @staticmethod
    def _validate_inputs(inputs: GoldenInputs) -> None:
        for field_name in (
            "apk",
            "il2cpp",
            "metadata",
            "catalog",
            "catalog_hash",
            "master_version",
            "asset_manifest",
        ):
            path = getattr(inputs, field_name)
            if not path.is_file():
                raise GoldenError(f"missing Golden input: {field_name}")
        if not inputs.master_root.is_dir():
            raise GoldenError("missing Golden input: master_root")
        if not any(inputs.master_root.glob("*.json")):
            raise GoldenError("master_root contains no JSON tables")
        for field_name in ("package_set_manifest", "client_profile"):
            path = getattr(inputs, field_name)
            if path is not None and not path.is_file():
                raise GoldenError(f"missing Golden input: {field_name}")

    @staticmethod
    def _read_version(path: Path, description: str) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise GoldenError(f"cannot read {description}") from exc
        if not value:
            raise GoldenError(f"{description} cannot be empty")
        return value

    @staticmethod
    def _statistics(
        master_rows: dict[str, int],
        asset_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        bundle_count = asset_manifest.get("bundle_count")
        assets = asset_manifest.get("assets")
        if type(bundle_count) is not int or bundle_count < 0:
            raise GoldenError("asset manifest bundle_count must be non-negative")
        if not isinstance(assets, list):
            raise GoldenError("asset manifest assets must be a list")
        return {
            "masterTableCount": len(master_rows),
            "masterRowCount": sum(master_rows.values()),
            "criticalTableRows": {
                name: master_rows[name] for name in CURRENT_SITE_MASTER_TABLES
            },
            "bundleCount": bundle_count,
            "extractedResourceCount": len(assets),
        }

    def _write_baseline(self, value: dict[str, Any]) -> None:
        self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._baseline_path.parent,
                prefix="baseline-",
                suffix=".part",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self._baseline_path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
