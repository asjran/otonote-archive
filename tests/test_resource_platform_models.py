from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    CanonicalEntity,
    CanonicalEvidence,
    ClientBuild,
    ContentRelease,
    EntityVariant,
    GateReason,
    JobCheckpoint,
    JobStatus,
    Region,
    SourceObject,
    VersionVector,
    content_release_id,
)
from tools.resource_pipeline.config import (  # noqa: E402
    load_environment_config,
    load_platform_config,
)


class VersionIdentityTest(unittest.TestCase):
    def test_version_vector_is_stable_and_release_identity_is_region_scoped(
        self,
    ) -> None:
        vector = VersionVector(
            client_version="0.9.0+8135",
            minimum_client_version=None,
            bootstrap_revision="bootstrap-7",
            catalog_hash="ecfcdb9b6c554f85bef9bf7597bb61a6",
            master_version=(
                "9c23d88a191e4648f0a28f4bbd4edb64"
                "03d5adf99ac5793efd7cc1cb3d49104c"
            ),
            asset_manifest_version=None,
            remote_code_hash=None,
        )

        self.assertEqual(
            vector.fingerprint(),
            "487f3cb609f79a2cf7549401b6e90019c406a5936ac447420348c4720fb71a8a",
        )
        self.assertEqual(
            content_release_id(Region.GLOBAL, Channel.STAGING, vector),
            "global-staging-487f3cb609f79a2c",
        )
        self.assertEqual(
            content_release_id(Region.GLOBAL, Channel.STAGING, vector),
            "global-staging-487f3cb609f79a2c",
        )

    def test_unknown_version_fields_are_distinct_from_empty_values(self) -> None:
        unknown_vector = VersionVector(
            client_version="0.9.0+8135",
            minimum_client_version=None,
            bootstrap_revision=None,
            catalog_hash=None,
            master_version=None,
            asset_manifest_version=None,
            remote_code_hash=None,
        )

        self.assertIsNone(unknown_vector.as_canonical_dict()["catalogHash"])
        with self.assertRaisesRegex(ValueError, "catalog_hash cannot be empty"):
            VersionVector(
                client_version="0.9.0+8135",
                minimum_client_version=None,
                bootstrap_revision=None,
                catalog_hash="",
                master_version=None,
                asset_manifest_version=None,
                remote_code_hash=None,
            )


class ClientBuildIdentityTest(unittest.TestCase):
    def test_client_build_identity_uses_region_channel_version_and_apk_hash(
        self,
    ) -> None:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.global.fixture",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="a" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="global-staging-fixture-basic",
        )

        self.assertEqual(
            build.id,
            "global-staging-android-8135-aaaaaaaaaaaaaaaa",
        )
        with self.assertRaisesRegex(ValueError, "package_sha256"):
            ClientBuild(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                platform="android",
                package_name="com.example.global.fixture",
                version_name="0.9.0",
                version_code=8135,
                package_sha256="not-a-sha256",
                unity_version="6000.3.12f1",
                client_generation="unity6000-il2cpp39-v1",
                auth_profile_ref="global-staging-fixture-basic",
            )
        with self.assertRaisesRegex(ValueError, "platform"):
            ClientBuild(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                platform="../android",
                package_name="com.example.global.fixture",
                version_name="0.9.0",
                version_code=8135,
                package_sha256="a" * 64,
                unity_version="6000.3.12f1",
                client_generation="unity6000-il2cpp39-v1",
                auth_profile_ref="global-staging-fixture-basic",
            )
        with self.assertRaisesRegex(ValueError, "version_code"):
            ClientBuild(
                region=Region.GLOBAL,
                channel=Channel.STAGING,
                platform="android",
                package_name="com.example.global.fixture",
                version_name="0.9.0",
                version_code=True,
                package_sha256="a" * 64,
                unity_version="6000.3.12f1",
                client_generation="unity6000-il2cpp39-v1",
                auth_profile_ref="global-staging-fixture-basic",
            )

    def test_content_release_inherits_server_identity_from_client_build(
        self,
    ) -> None:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.global.fixture",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="b" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="global-staging-fixture-basic",
        )
        vector = VersionVector(
            client_version="0.9.0+8135",
            minimum_client_version=None,
            bootstrap_revision=None,
            catalog_hash="catalog-2",
            master_version="master-9",
            asset_manifest_version=None,
            remote_code_hash=None,
        )

        release = ContentRelease.for_client_build(build, vector)

        self.assertEqual(release.region, Region.GLOBAL)
        self.assertEqual(release.channel, Channel.STAGING)
        self.assertEqual(release.observed_by_client_build_ref, build.id)
        self.assertEqual(
            release.id,
            content_release_id(Region.GLOBAL, Channel.STAGING, vector),
        )


class PipelineRecordTest(unittest.TestCase):
    def test_source_object_requires_verified_hash_size_and_visibility(self) -> None:
        source = SourceObject(
            sha256="c" * 64,
            byte_size=4096,
            media_type="application/octet-stream",
            source_uri="https://assets.example.test/bundle",
            visibility="private",
        )

        self.assertEqual(source.sha256, "c" * 64)
        with self.assertRaisesRegex(ValueError, "visibility"):
            SourceObject(
                sha256="c" * 64,
                byte_size=4096,
                media_type="application/octet-stream",
                source_uri="https://assets.example.test/bundle",
                visibility="world-readable",
            )

    def test_canonical_entity_requires_cross_variant_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence"):
            CanonicalEntity(
                id="song-canonical-1",
                variant_refs=("jp-song-1", "global-song-9"),
                evidence=(),
            )
        with self.assertRaisesRegex(ValueError, "unsupported evidence kind"):
            CanonicalEvidence(kind="matchingName", value="Same title")

        entity = CanonicalEntity(
            id="song-canonical-1",
            variant_refs=("jp-song-1", "global-song-9"),
            evidence=(
                CanonicalEvidence(
                    kind="matchingAssetSha256",
                    value="d" * 64,
                ),
            ),
        )

        self.assertEqual(len(entity.variant_refs), 2)

    def test_entity_variant_inherits_release_identity_and_keeps_locales(self) -> None:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.global.fixture",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="e" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="global-staging-fixture-basic",
        )
        release = ContentRelease.for_client_build(
            build,
            VersionVector(
                client_version="0.9.0+8135",
                minimum_client_version=None,
                bootstrap_revision=None,
                catalog_hash="catalog-3",
                master_version="master-10",
                asset_manifest_version=None,
                remote_code_hash=None,
            ),
        )

        variant = EntityVariant.for_release(
            release,
            entity_type="music",
            source_master_id="1001",
            availability="available",
            localized_text={"ja": "曲名", "en": "Song title"},
        )

        self.assertEqual(variant.region, Region.GLOBAL)
        self.assertEqual(variant.channel, Channel.STAGING)
        self.assertEqual(
            variant.localized_text_dict(),
            {"en": "Song title", "ja": "曲名"},
        )

    def test_checkpoint_requires_reason_for_manual_gate_status(self) -> None:
        reason = GateReason(
            code="needs_auth_material",
            summary="environment credentials are unavailable",
            retry_from_stage="bootstrap",
        )
        checkpoint = JobCheckpoint(
            job_id="job-1",
            environment_id="global-staging-fixture",
            content_release_ref=None,
            status=JobStatus.NEEDS_AUTH_MATERIAL,
            completed_stages=("discovered",),
            gate_reason=reason,
        )

        self.assertEqual(checkpoint.gate_reason, reason)
        with self.assertRaisesRegex(ValueError, "requires a gate_reason"):
            JobCheckpoint(
                job_id="job-2",
                environment_id="global-staging-fixture",
                content_release_ref=None,
                status=JobStatus.NEEDS_AUTH_MATERIAL,
                completed_stages=("discovered",),
                gate_reason=None,
            )


class PlatformConfigTest(unittest.TestCase):
    def test_repository_platform_config_uses_private_data_root(self) -> None:
        config = load_platform_config(
            REPO_ROOT / "config/resource-platform.toml",
            project_root=REPO_ROOT,
        )

        self.assertEqual(config.data_root, REPO_ROOT / "data")
        self.assertFalse(config.auto_publish)

    def test_loads_typed_platform_settings_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "config"
            config_dir.mkdir()
            path = config_dir / "resource-platform.toml"
            path.write_text(
                """
[storage]
dataRoot = "data"

[download]
maxConcurrency = 4
connectTimeoutSeconds = 10
readTimeoutSeconds = 60
retryLimit = 3

[publishing]
autoPublish = false

[validation]
maxCriticalTableDropRatio = 0.5
""".strip(),
                encoding="utf-8",
            )

            config = load_platform_config(path, project_root=root)

            self.assertEqual(config.data_root, root / "data")
            self.assertEqual(config.max_download_concurrency, 4)
            self.assertEqual(config.connect_timeout_seconds, 10)
            self.assertEqual(config.read_timeout_seconds, 60)
            self.assertEqual(config.retry_limit, 3)
            self.assertFalse(config.auto_publish)
            self.assertEqual(config.max_critical_table_drop_ratio, 0.5)

    def test_platform_config_rejects_string_encoded_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "resource-platform.toml"
            path.write_text(
                """
[storage]
dataRoot = "data"
[download]
maxConcurrency = "4"
connectTimeoutSeconds = 10
readTimeoutSeconds = 60
retryLimit = 3
[publishing]
autoPublish = false
[validation]
maxCriticalTableDropRatio = 0.5
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "download.maxConcurrency must be an integer",
            ):
                load_platform_config(path, project_root=root)

    def test_loads_confirmed_jp_staging_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "global-staging-fixture.toml"
            path.write_text(
                """
environmentId = "global-staging-fixture"
region = "global"
channel = "staging"
enabled = true
clientBuildRef = "global-staging-android-8135-aaaaaaaaaaaaaaaa"
clientGeneration = "unity6000-il2cpp39-v1"
adapter = "protocol_pending"
allowedHosts = ["assets.example.test", "master.example.test"]
authProfileRef = "global-staging-fixture-basic"
pollIntervalSeconds = 900
""".strip(),
                encoding="utf-8",
            )

            environment = load_environment_config(path)

            self.assertEqual(environment.environment_id, "global-staging-fixture")
            self.assertEqual(environment.region, Region.GLOBAL)
            self.assertEqual(environment.channel, Channel.STAGING)
            self.assertTrue(environment.enabled)
            self.assertEqual(
                environment.client_build_ref,
                "global-staging-android-8135-aaaaaaaaaaaaaaaa",
            )
            self.assertEqual(
                environment.allowed_hosts,
                ("assets.example.test", "master.example.test"),
            )

    def test_environment_rejects_cross_channel_client_build_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad-environment.toml"
            path.write_text(
                """
environmentId = "global-staging-fixture"
region = "global"
channel = "staging"
enabled = true
clientBuildRef = "global-production-android-8135-aaaaaaaaaaaaaaaa"
clientGeneration = "unity6000-il2cpp39-v1"
adapter = "protocol_pending"
allowedHosts = ["assets.example.test"]
authProfileRef = "global-staging-fixture-basic"
pollIntervalSeconds = 900
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "clientBuildRef must belong to global/staging",
            ):
                load_environment_config(path)

    def test_environment_rejects_inline_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe-environment.toml"
            path.write_text(
                """
environmentId = "global-staging-fixture"
region = "global"
channel = "staging"
enabled = true
clientBuildRef = "global-staging-android-8135-aaaaaaaaaaaaaaaa"
clientGeneration = "unity6000-il2cpp39-v1"
adapter = "protocol_pending"
allowedHosts = ["assets.example.test"]
authProfileRef = "global-staging-fixture-basic"
pollIntervalSeconds = 900
basicAuthPassword = "must-not-be-here"
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "inline secret field is forbidden: basicAuthPassword",
            ):
                load_environment_config(path)


if __name__ == "__main__":
    unittest.main()
