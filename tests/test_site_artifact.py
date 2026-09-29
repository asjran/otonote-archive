from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.site_artifact import (  # noqa: E402
    ArtifactError,
    build_artifact,
    main,
    verify_artifact,
)


class SiteArtifactTest(unittest.TestCase):
    @staticmethod
    def build_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
        artifact_root = root / "dist"
        artifact_root.mkdir()
        (artifact_root / "index.html").write_text("<h1>OurNotes</h1>")
        (artifact_root / "app.js").write_text("console.log('ok')")
        (artifact_root / "favicon.svg").write_text("<svg/>")
        media_root = artifact_root / "media"
        media_root.mkdir()
        (media_root / "track.flac").write_bytes(b"large-media")
        data_root = artifact_root / "data"
        data_root.mkdir()
        media_index = data_root / "media-index.json"
        media_index.write_text(
            json.dumps({"schemaVersion": 1, "recordCount": 1})
        )
        release_index = root / "release-index.json"
        release_index.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "projections": [
                        {
                            "region": "global",
                            "channel": "staging",
                            "locale": "zh-CN",
                            "contentReleaseId": "global-staging-release",
                        }
                    ],
                }
            )
        )
        package_lock = root / "package-lock.json"
        package_lock.write_text('{"lockfileVersion": 3}\n')
        return artifact_root, release_index, package_lock, media_index

    @staticmethod
    def build_release(
        artifact_root: Path,
        release_index: Path,
        package_lock: Path,
        media_index: Path,
    ) -> dict[str, object]:
        return build_artifact(
            artifact_root=artifact_root,
            release_index=release_index,
            package_lock=package_lock,
            media_index=media_index,
            schemas={"catalog.json": 6, "media-index.json": 1},
            site_release_id="site-release",
            git_commit="a" * 40,
            docker_image="ournotes:test",
            built_at="2026-07-26T12:00:00Z",
        )

    def test_build_writes_identity_and_core_file_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )

            identity = self.build_release(
                artifact_root, release_index, package_lock, media_index
            )

            release = json.loads(
                (artifact_root / ".release.json").read_text()
            )
            manifest_bytes = (
                artifact_root / "artifact-manifest.json"
            ).read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertEqual(release, identity)
            self.assertEqual(release["schemaVersion"], 2)
            self.assertEqual(release["siteReleaseId"], "site-release")
            self.assertEqual(release["gitCommit"], "a" * 40)
            self.assertEqual(
                release["contentReleases"],
                [
                    {
                        "channel": "staging",
                        "id": "global-staging-release",
                        "region": "global",
                    }
                ],
            )
            self.assertEqual(
                release["packageLockSha256"],
                hashlib.sha256(package_lock.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                release["artifactManifestSha256"],
                hashlib.sha256(manifest_bytes).hexdigest(),
            )
            self.assertEqual(
                release["schemas"],
                {"catalog.json": 6, "media-index.json": 1},
            )
            self.assertEqual(
                [item["path"] for item in manifest["files"]],
                [
                    "app.js",
                    "data/media-index.json",
                    "favicon.svg",
                    "index.html",
                ],
            )
            self.assertNotIn(
                "media/track.flac",
                [item["path"] for item in manifest["files"]],
            )
            self.assertEqual(release["media"]["fileCount"], 1)
            self.assertEqual(
                release["media"]["indexSha256"],
                hashlib.sha256(media_index.read_bytes()).hexdigest(),
            )

    def test_build_rejects_private_anontokyo_content_before_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            private_route = artifact_root / "private-preview/anontokyo"
            private_route.mkdir(parents=True)
            (private_route / "index.html").write_text(
                "PRIVATE LOCAL PREVIEW", encoding="utf-8"
            )

            with self.assertRaisesRegex(ArtifactError, "private content"):
                self.build_release(
                    artifact_root, release_index, package_lock, media_index
                )

            self.assertFalse((artifact_root / "artifact-manifest.json").exists())

    def test_verify_rejects_changed_core_file_and_wrong_expected_git(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            self.build_release(
                artifact_root, release_index, package_lock, media_index
            )

            verified = verify_artifact(
                artifact_root,
                expected_git_commit="a" * 40,
                package_lock=package_lock,
            )
            self.assertEqual(verified["siteReleaseId"], "site-release")

            with self.assertRaisesRegex(ArtifactError, "Git commit"):
                verify_artifact(
                    artifact_root,
                    expected_git_commit="b" * 40,
                    package_lock=package_lock,
                )

            (artifact_root / "app.js").write_text("tampered")
            with self.assertRaisesRegex(ArtifactError, "manifest"):
                verify_artifact(
                    artifact_root,
                    expected_git_commit="a" * 40,
                    package_lock=package_lock,
                )

    def test_nested_media_route_is_hashed_as_a_core_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            route = artifact_root / "global/zh-CN/resources/media"
            route.mkdir(parents=True)
            page = route / "index.html"
            page.write_text("<h1>Media archive</h1>")
            self.build_release(
                artifact_root, release_index, package_lock, media_index
            )

            manifest = json.loads(
                (artifact_root / "artifact-manifest.json").read_text()
            )
            self.assertIn(
                "global/zh-CN/resources/media/index.html",
                [item["path"] for item in manifest["files"]],
            )
            page.write_text("<h1>Tamper archive</h1>")
            with self.assertRaisesRegex(ArtifactError, "manifest"):
                verify_artifact(artifact_root)

    def test_system_metadata_never_changes_artifact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            root_metadata = artifact_root / ".DS_Store"
            media_metadata = artifact_root / "media/.DS_Store"
            root_metadata.write_bytes(b"finder-root")
            media_metadata.write_bytes(b"finder-media")

            identity = self.build_release(
                artifact_root, release_index, package_lock, media_index
            )
            root_metadata.write_bytes(b"changed-root-metadata")
            media_metadata.write_bytes(b"changed-media-metadata")

            verified = verify_artifact(artifact_root)
            self.assertEqual(verified, identity)
            manifest = json.loads(
                (artifact_root / "artifact-manifest.json").read_text()
            )
            self.assertNotIn(
                ".DS_Store",
                [item["path"] for item in manifest["files"]],
            )

    def test_symlinks_are_recorded_but_cannot_escape_the_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            locale_root = artifact_root / "global" / "zh-CN"
            locale_root.mkdir(parents=True)
            (locale_root / "index.html").write_text("localized")
            (artifact_root / "localized.html").symlink_to("global/zh-CN/index.html")

            self.build_release(
                artifact_root, release_index, package_lock, media_index
            )
            manifest = json.loads(
                (artifact_root / "artifact-manifest.json").read_text()
            )
            self.assertEqual(
                manifest["symlinks"],
                [
                    {
                        "path": "localized.html",
                        "target": "global/zh-CN/index.html",
                    }
                ],
            )

            (artifact_root / "leak.json").symlink_to(release_index)
            with self.assertRaisesRegex(ArtifactError, "outside"):
                build_artifact(
                    artifact_root=artifact_root,
                    release_index=release_index,
                    package_lock=package_lock,
                    media_index=media_index,
                    schemas={"media-index.json": 1},
                    site_release_id="unsafe-release",
                    git_commit="a" * 40,
                    docker_image="ournotes:test",
                    built_at="2026-07-26T12:00:00Z",
                )

    def test_verify_rejects_an_unsafe_release_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            self.build_release(
                artifact_root, release_index, package_lock, media_index
            )
            release_path = artifact_root / ".release.json"
            release = json.loads(release_path.read_text())
            release["siteReleaseId"] = "../../outside"
            release_path.write_text(json.dumps(release))

            with self.assertRaisesRegex(ArtifactError, "siteReleaseId"):
                verify_artifact(artifact_root)

    def test_verify_rejects_mismatched_content_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            self.build_release(
                artifact_root, release_index, package_lock, media_index
            )
            release_value = json.loads(release_index.read_text())
            release_value["projections"][0][
                "contentReleaseId"
            ] = "global-staging-new-release"
            release_index.write_text(json.dumps(release_value))

            with self.assertRaisesRegex(ArtifactError, "ContentRelease"):
                verify_artifact(
                    artifact_root,
                    release_index=release_index,
                )

    def test_cli_build_then_verify_prints_the_immutable_release_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            self.assertEqual(
                main(
                    [
                        "build",
                        "--artifact-root",
                        str(artifact_root),
                        "--release-index",
                        str(release_index),
                        "--package-lock",
                        str(package_lock),
                        "--media-index",
                        str(media_index),
                        "--site-release-id",
                        "cli-release",
                        "--git-commit",
                        "c" * 40,
                        "--docker-image",
                        "ournotes:cli",
                        "--built-at",
                        "2026-07-26T13:00:00Z",
                    ]
                ),
                0,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "verify",
                        "--artifact-root",
                        str(artifact_root),
                        "--expected-git-commit",
                        "c" * 40,
                        "--package-lock",
                        str(package_lock),
                        "--print-site-release-id",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue().strip(), "cli-release")

    def test_skip_build_rejects_stale_identity_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            self.assertEqual(
                main(
                    [
                        "build",
                        "--artifact-root",
                        str(artifact_root),
                        "--release-index",
                        str(release_index),
                        "--package-lock",
                        str(package_lock),
                        "--media-index",
                        str(media_index),
                        "--site-release-id",
                        "stale-release",
                        "--git-commit",
                        "0" * 40,
                        "--docker-image",
                        "ournotes:stale",
                        "--built-at",
                        "2026-07-26T13:00:00Z",
                    ]
                ),
                0,
            )
            release_path = artifact_root / ".release.json"
            original_identity = release_path.read_bytes()
            marker = root / "ssh-invoked"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                '#!/usr/bin/env bash\n'
                'printf invoked >"${OURNOTES_TEST_SSH_MARKER}"\n'
                "exit 99\n"
            )
            fake_ssh.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "OURNOTES_DIST_DIR": str(artifact_root),
                    "OURNOTES_PACKAGE_LOCK": str(package_lock),
                    "OURNOTES_RELEASE_INDEX": str(release_index),
                    "OURNOTES_TEST_SSH_MARKER": str(marker),
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                }
            )

            completed = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "tools/deploy_site.sh"),
                    "--skip-build",
                ],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Git commit", completed.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(release_path.read_bytes(), original_identity)

    def test_skip_build_verifies_valid_identity_before_remote_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root, release_index, package_lock, media_index = (
                self.build_fixture(root)
            )
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
            ).strip()
            self.assertEqual(
                main(
                    [
                        "build",
                        "--artifact-root",
                        str(artifact_root),
                        "--release-index",
                        str(release_index),
                        "--package-lock",
                        str(package_lock),
                        "--media-index",
                        str(media_index),
                        "--site-release-id",
                        "verified-release",
                        "--git-commit",
                        git_commit,
                        "--docker-image",
                        "ournotes:verified",
                        "--built-at",
                        "2026-07-26T13:00:00Z",
                    ]
                ),
                0,
            )
            release_path = artifact_root / ".release.json"
            original_identity = release_path.read_bytes()
            marker = root / "ssh-invoked"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                '#!/usr/bin/env bash\n'
                'printf invoked >"${OURNOTES_TEST_SSH_MARKER}"\n'
                "exit 99\n"
            )
            fake_ssh.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "OURNOTES_DIST_DIR": str(artifact_root),
                    "OURNOTES_PACKAGE_LOCK": str(package_lock),
                    "OURNOTES_RELEASE_INDEX": str(release_index),
                    "OURNOTES_TEST_SSH_MARKER": str(marker),
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                }
            )

            completed = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "tools/deploy_site.sh"),
                    "--skip-build",
                ],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 99)
            self.assertTrue(marker.is_file())
            self.assertEqual(release_path.read_bytes(), original_identity)


if __name__ == "__main__":
    unittest.main()
