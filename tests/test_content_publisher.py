from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    Region,
    VersionVector,
)
from tools.resource_pipeline.publisher import (  # noqa: E402
    ContentPublisher,
    ContentReleaseRef,
    PublishError,
    SiteRelease,
)
from tools.resource_pipeline.release_repository import (  # noqa: E402
    ReleaseRepository,
)
from tools.site_artifact import build_artifact  # noqa: E402


class ContentPublisherTest(unittest.TestCase):
    @staticmethod
    def release(
        catalog_hash: str,
        *,
        region: Region = Region.GLOBAL,
        channel: Channel = Channel.STAGING,
    ) -> ContentRelease:
        build = ClientBuild(
            region=region,
            channel=channel,
            platform="android",
            package_name="com.example.staging",
            version_name="1.0.0",
            version_code=1,
            package_sha256="a" * 64,
            unity_version="6000.3.12f1",
            client_generation="fixture-v1",
            auth_profile_ref="fixture-auth",
        )
        return ContentRelease.for_client_build(
            build,
            VersionVector(
                client_version="1.0.0+1",
                minimum_client_version=None,
                bootstrap_revision="bootstrap-1",
                catalog_hash=catalog_hash,
                master_version="master-1",
                asset_manifest_version=None,
                remote_code_hash=None,
            ),
        )

    @staticmethod
    def site_release(site_id: str, release: ContentRelease) -> SiteRelease:
        return SiteRelease(
            id=site_id,
            content_releases=(
                ContentReleaseRef(
                    region=release.region,
                    channel=release.channel,
                    id=release.id,
                ),
            ),
            git_commit="a" * 40,
            docker_image="ournotes-resource-worker:test",
            built_at="2026-07-18T08:00:00Z",
        )

    @staticmethod
    def candidate(root: Path, name: str) -> Path:
        path = root / name
        path.mkdir()
        (path / "index.html").write_text(name, encoding="utf-8")
        return path

    def test_failed_static_check_does_not_change_site_or_content_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            old_content = self.release("catalog-old")
            new_content = self.release("catalog-new")
            repository.create_candidate(old_content, {"objects": []})
            repository.create_candidate(new_content, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            old_site = self.site_release("site-old", old_content)
            publisher.publish(
                self.candidate(root, "old-candidate"),
                old_site,
                static_check=lambda _: True,
                health_check=lambda _: True,
            )

            with self.assertRaisesRegex(PublishError, "static check"):
                publisher.publish(
                    self.candidate(root, "new-candidate"),
                    self.site_release("site-new", new_content),
                    static_check=lambda _: False,
                    health_check=lambda _: True,
                )

            self.assertEqual(
                (root / "site-releases/current").resolve().name,
                "site-old",
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                old_content.id,
            )

    def test_failed_health_check_rolls_back_site_and_content_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            old_content = self.release("catalog-old")
            new_content = self.release("catalog-new")
            repository.create_candidate(old_content, {"objects": []})
            repository.create_candidate(new_content, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            publisher.publish(
                self.candidate(root, "old-candidate"),
                self.site_release("site-old", old_content),
                static_check=lambda _: True,
                health_check=lambda _: True,
            )

            with self.assertRaisesRegex(PublishError, "health check"):
                publisher.publish(
                    self.candidate(root, "new-candidate"),
                    self.site_release("site-new", new_content),
                    static_check=lambda _: True,
                    health_check=lambda _: False,
                )

            self.assertEqual(
                (root / "site-releases/current").resolve().name,
                "site-old",
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                old_content.id,
            )

    def test_success_publishes_manifest_and_advances_both_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            content = self.release("catalog-current")
            repository.create_candidate(content, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            site = self.site_release("site-current", content)

            published = publisher.publish(
                self.candidate(root, "candidate"),
                site,
                static_check=lambda path: (path / "index.html").is_file(),
                health_check=lambda path: (path / "index.html").is_file(),
            )

            manifest = json.loads(
                (published / ".release.json").read_text(encoding="utf-8")
            )["siteRelease"]
            self.assertEqual(manifest["id"], "site-current")
            self.assertEqual(manifest["gitCommit"], "a" * 40)
            self.assertEqual(
                manifest["dockerImage"],
                "ournotes-resource-worker:test",
            )
            self.assertEqual(
                manifest["contentReleases"],
                [
                    {
                        "id": content.id,
                        "region": "global",
                        "channel": "staging",
                    }
                ],
            )
            self.assertEqual(
                (root / "site-releases/current").resolve(),
                published.resolve(),
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                content.id,
            )

    def test_rollback_restores_site_and_content_from_previous_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            old_content = self.release("catalog-old")
            new_content = self.release("catalog-new")
            repository.create_candidate(old_content, {"objects": []})
            repository.create_candidate(new_content, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            publisher.publish(
                self.candidate(root, "old-candidate"),
                self.site_release("site-old", old_content),
                static_check=lambda _: True,
                health_check=lambda _: True,
            )
            publisher.publish(
                self.candidate(root, "new-candidate"),
                self.site_release("site-new", new_content),
                static_check=lambda _: True,
                health_check=lambda _: True,
            )

            restored = publisher.rollback(
                health_check=lambda path: (path / "index.html").is_file()
            )

            self.assertEqual(restored.name, "site-old")
            self.assertEqual(
                (root / "site-releases/current").resolve().name,
                "site-old",
            )
            self.assertEqual(
                (root / "site-releases/previous").resolve().name,
                "site-new",
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                old_content.id,
            )

    def test_multi_server_pointer_failure_restores_every_content_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            old_jp = self.release("jp-old")
            old_global = self.release(
                "global-old",
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
            )
            new_jp = self.release("jp-new")
            for release in (old_jp, old_global, new_jp):
                repository.create_candidate(release, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            old_site = SiteRelease(
                id="site-old",
                content_releases=(
                    ContentReleaseRef(Region.GLOBAL, Channel.STAGING, old_jp.id),
                    ContentReleaseRef(
                        Region.GLOBAL,
                        Channel.PRODUCTION,
                        old_global.id,
                    ),
                ),
                git_commit="a" * 40,
                docker_image="ournotes-resource-worker:test",
                built_at="2026-07-18T08:00:00Z",
            )
            publisher.publish(
                self.candidate(root, "old-candidate"),
                old_site,
                static_check=lambda _: True,
                health_check=lambda _: True,
            )
            broken_site = SiteRelease(
                id="site-broken",
                content_releases=(
                    ContentReleaseRef(Region.GLOBAL, Channel.STAGING, new_jp.id),
                    ContentReleaseRef(
                        Region.GLOBAL,
                        Channel.PRODUCTION,
                        "global-production-missing",
                    ),
                ),
                git_commit="b" * 40,
                docker_image="ournotes-resource-worker:test",
                built_at="2026-07-18T09:00:00Z",
            )

            with self.assertRaisesRegex(PublishError, "pointer update"):
                publisher.publish(
                    self.candidate(root, "broken-candidate"),
                    broken_site,
                    static_check=lambda _: True,
                    health_check=lambda _: True,
                )

            self.assertEqual(
                (root / "site-releases/current").resolve().name,
                "site-old",
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                old_jp.id,
            )
            self.assertEqual(
                repository.current_release_id(
                    Region.GLOBAL,
                    Channel.PRODUCTION,
                ),
                old_global.id,
            )

    def test_private_or_symlinked_objects_cannot_enter_the_web_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            content = self.release("catalog-private-check")
            repository.create_candidate(content, {"objects": []})
            candidate = self.candidate(root, "candidate")
            private_file = root / "private-master.json"
            private_file.write_text("private", encoding="utf-8")
            (candidate / "master-leak.json").symlink_to(private_file)
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )

            with self.assertRaisesRegex(PublishError, "private object"):
                publisher.publish(
                    candidate,
                    self.site_release("site-private", content),
                    static_check=lambda _: True,
                    health_check=lambda _: True,
                )

            self.assertFalse((root / "site-releases/current").exists())
            self.assertIsNone(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING)
            )

    def test_site_release_manifest_deduplicates_locales_from_release_index(
        self,
    ) -> None:
        release_index = {
            "schemaVersion": 1,
            "active": {},
            "projections": [
                {
                    "contentReleaseId": "global-staging-release",
                    "region": "global",
                    "channel": "staging",
                    "locale": "en",
                },
                {
                    "contentReleaseId": "global-staging-release",
                    "region": "global",
                    "channel": "staging",
                    "locale": "zh-CN",
                },
                {
                    "contentReleaseId": "global-production-release",
                    "region": "global",
                    "channel": "production",
                    "locale": "en",
                },
            ],
        }

        release = SiteRelease.from_release_index(
            site_release_id="site-matrix",
            release_index=release_index,
            git_commit="c" * 40,
            docker_image="ournotes-resource-worker:commit-c",
            built_at="2026-07-18T10:00:00Z",
        )

        self.assertEqual(
            [item.to_dict() for item in release.content_releases],
            [
                {
                    "id": "global-production-release",
                    "region": "global",
                    "channel": "production",
                },
                {
                    "id": "global-staging-release",
                    "region": "global",
                    "channel": "staging",
                },
            ],
        )

    def test_site_release_reader_supports_v2_identity_for_diagnostics(self) -> None:
        manifest = {
            "schemaVersion": 2,
            "siteReleaseId": "site-v2",
            "gitCommit": "d" * 40,
            "dockerImage": "ournotes-resource-worker:v2",
            "builtAt": "2026-07-26T12:00:00Z",
            "contentReleases": [
                {
                    "id": "global-staging-release",
                    "region": "global",
                    "channel": "staging",
                }
            ],
            "packageLockSha256": "e" * 64,
            "artifactManifestSha256": "f" * 64,
            "schemas": {"catalog.json": 6},
            "fileCount": 3,
            "totalBytes": 42,
            "media": {
                "indexPath": "data/media-index.json",
                "indexSha256": "1" * 64,
                "fileCount": 1,
                "totalBytes": 12,
            },
        }

        release = SiteRelease.from_manifest(manifest)

        self.assertEqual(release.id, "site-v2")
        self.assertEqual(release.git_commit, "d" * 40)
        self.assertEqual(release.content_releases[0].id, "global-staging-release")

    def test_publisher_preserves_a_verified_v2_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            content = self.release("catalog-v2")
            repository.create_candidate(content, {"objects": []})
            site = self.site_release("site-v2", content)
            candidate = self.candidate(root, "candidate-v2")
            data_root = candidate / "data"
            data_root.mkdir()
            media_index = data_root / "media-index.json"
            media_index.write_text(
                json.dumps({"schemaVersion": 1, "recordCount": 0})
            )
            release_index = root / "release-index.json"
            release_index.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "projections": [
                            {
                                "region": content.region.value,
                                "channel": content.channel.value,
                                "locale": "zh-CN",
                                "contentReleaseId": content.id,
                            }
                        ],
                    }
                )
            )
            package_lock = root / "package-lock.json"
            package_lock.write_text('{"lockfileVersion": 3}\n')
            build_artifact(
                artifact_root=candidate,
                release_index=release_index,
                package_lock=package_lock,
                media_index=media_index,
                schemas={"media-index.json": 1},
                site_release_id=site.id,
                git_commit=site.git_commit,
                docker_image=site.docker_image,
                built_at=site.built_at,
            )
            original_identity = (candidate / ".release.json").read_bytes()
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )

            published = publisher.publish(
                candidate,
                site,
                static_check=lambda _: True,
                health_check=lambda _: True,
            )

            self.assertEqual(
                (published / ".release.json").read_bytes(),
                original_identity,
            )
            self.assertTrue((published / "artifact-manifest.json").is_file())

    def test_malformed_previous_manifest_cannot_change_live_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            old_content = self.release("catalog-old")
            new_content = self.release("catalog-new")
            repository.create_candidate(old_content, {"objects": []})
            repository.create_candidate(new_content, {"objects": []})
            publisher = ContentPublisher(
                site_root=root / "site-releases",
                content_repository=repository,
            )
            publisher.publish(
                self.candidate(root, "old-candidate"),
                self.site_release("site-old", old_content),
                static_check=lambda _: True,
                health_check=lambda _: True,
            )
            publisher.publish(
                self.candidate(root, "new-candidate"),
                self.site_release("site-new", new_content),
                static_check=lambda _: True,
                health_check=lambda _: True,
            )
            previous_manifest = (
                root / "site-releases/releases/site-old/.release.json"
            )
            malformed = json.loads(previous_manifest.read_text(encoding="utf-8"))
            malformed["siteRelease"]["contentReleases"][0]["id"] = 42
            previous_manifest.write_text(json.dumps(malformed), encoding="utf-8")

            with self.assertRaisesRegex(PublishError, "manifest"):
                publisher.rollback(health_check=lambda _: True)

            self.assertEqual(
                (root / "site-releases/current").resolve().name,
                "site-new",
            )
            self.assertEqual(
                repository.current_release_id(Region.GLOBAL, Channel.STAGING),
                new_content.id,
            )


if __name__ == "__main__":
    unittest.main()
