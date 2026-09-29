from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.anontokyo_private_preview import (  # noqa: E402
    AnonTokyoPrivatePreviewError,
    build_private_preview,
)


FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/anontokyo/minimal"


class AnonTokyoPrivatePreviewTest(unittest.TestCase):
    def test_stages_only_hash_verified_audio_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_root = root / "audio"
            audio_root.mkdir()
            audio_file = audio_root / "AT_Bgm_Music.mp3"
            audio_file.write_bytes(b"verified-audio")
            digest = hashlib.sha256(audio_file.read_bytes()).hexdigest()
            audio_manifest = audio_root / "manifest.json"
            audio_manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "tracks": [
                            {
                                "logicalKey": "AT_Bgm_Music",
                                "title": "AnonTokyo 店铺音乐",
                                "file": audio_file.name,
                                "sha256": digest,
                                "durationSeconds": 44.27,
                                "quality": "passed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = build_private_preview(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                map_config_path=FIXTURE_ROOT / "MapConfig_1.json",
                audio_manifest_path=audio_manifest,
                media_root=None,
                output_root=root / "private-output",
                source_release_id="global-staging-fixture-audio",
                site_root=REPO_ROOT / "site",
                build_site=False,
                generated_at="2026-08-05T00:00:00Z",
            )

            staged = json.loads(
                (result.public_root / "anontokyo-media.json").read_text()
            )
            self.assertEqual(staged[0]["logicalKey"], "AT_Bgm_Music")
            self.assertEqual(staged[0]["kind"], "audio")
            self.assertEqual(staged[0]["sha256"], digest)
            staged_file = result.public_root / staged[0]["publicUrl"].removeprefix("/")
            self.assertEqual(staged_file.read_bytes(), b"verified-audio")
            self.assertEqual(result.staged_media_count, 1)
            self.assertEqual(result.staged_media_bytes, len(b"verified-audio"))

    def test_builds_studio_when_map_config_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = build_private_preview(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                map_config_path=FIXTURE_ROOT / "MapConfig_1.json",
                media_root=None,
                output_root=root / "private-output",
                source_release_id="global-staging-fixture-studio",
                site_root=REPO_ROOT / "site",
                build_site=False,
                generated_at="2026-08-05T00:00:00Z",
            )

            studio = json.loads(
                (result.player_guide_root / "studio.json").read_text()
            )
            acceptance = json.loads(result.acceptance_path.read_text())
            self.assertEqual(studio["storeSizes"][0]["width"], 4)
            self.assertEqual(acceptance["playerRecordCounts"]["studioFurniture"], 2)
            self.assertEqual(acceptance["recordCounts"]["mapTiles"], 16)

    def test_rejects_unsafe_release_id_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private-output"
            with self.assertRaisesRegex(
                AnonTokyoPrivatePreviewError, "path-safe lowercase"
            ):
                build_private_preview(
                    master_root=FIXTURE_ROOT / "master",
                    catalog_path=FIXTURE_ROOT / "catalog.json",
                    media_root=None,
                    output_root=output,
                    source_release_id="../public",
                    site_root=REPO_ROOT / "site",
                    build_site=False,
                )
            self.assertFalse(output.exists())

    def test_rejects_private_output_inside_site_tree(self) -> None:
        with self.assertRaisesRegex(
            AnonTokyoPrivatePreviewError, "outside the site tree"
        ):
            build_private_preview(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                media_root=None,
                output_root=REPO_ROOT / "site/private-output",
                source_release_id="global-staging-fixture",
                site_root=REPO_ROOT / "site",
                build_site=False,
            )

    def test_cli_can_run_directly_from_repository_root(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "tools/anontokyo_private_preview.py",
                "--help",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("local-only AnonTokyo guide preview", completed.stdout)

    def test_builds_isolated_release_without_touching_site_public(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protected = root / "site-public"
            protected.mkdir()
            marker = protected / "keep.txt"
            marker.write_text("unchanged", encoding="utf-8")

            result = build_private_preview(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                media_root=None,
                output_root=root / "private-output",
                source_release_id="global-staging-fixture",
                site_root=REPO_ROOT / "site",
                build_site=False,
                generated_at="2026-08-05T00:00:00Z",
            )

            self.assertTrue(result.release_root.is_absolute())
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertTrue((result.release_root / "projection/manifest.json").is_file())
            self.assertTrue((result.release_root / "player-guide/manifest.json").is_file())
            self.assertEqual(result.player_guide_root, result.release_root / "player-guide")
            acceptance = json.loads(result.acceptance_path.read_text())
            self.assertEqual(acceptance["publicationState"], "private_preview")
            self.assertEqual(acceptance["recordCounts"]["goods"], 1)
            self.assertEqual(acceptance["playerRecordCounts"]["goods"], 1)
            self.assertEqual(acceptance["playerRecordCounts"]["furniture"], 2)
            self.assertEqual(acceptance["playerRecordCounts"]["themes"], 1)
            self.assertEqual(acceptance["playerRecordCounts"]["stages"], 1)
            self.assertEqual(acceptance["playerRecordCounts"]["chatCombinations"], 1)
            self.assertEqual(acceptance["playerRecordCounts"]["monologues"], 3)
            self.assertEqual(acceptance["hiddenTasks"], 0)
            self.assertEqual(acceptance["hiddenGoods"], 0)
            self.assertEqual(acceptance["hiddenFurniture"], 1)
            self.assertEqual(acceptance["unresolvedThemeFurniture"], 0)
            self.assertEqual(acceptance["hiddenStages"], 0)
            self.assertEqual(acceptance["hiddenMonologues"], 1)
            self.assertEqual(acceptance["hiddenChatScenes"], 0)
            self.assertEqual(acceptance["reusedChatCombinations"], 0)
            self.assertEqual(acceptance["furnitureWithImages"], 2)
            self.assertEqual(acceptance["charactersWithImages"], 2)
            self.assertEqual(acceptance["themesWithImages"], 1)
            self.assertEqual(acceptance["stagesWithImages"], 1)
            self.assertEqual(acceptance["feverEffects"], 1)
            self.assertEqual(acceptance["stagedMediaCount"], 0)
            self.assertEqual(acceptance["stagedMediaBytes"], 0)
            self.assertFalse((REPO_ROOT / "site/private-preview").exists())

    def test_stages_only_referenced_images_across_all_player_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            media.mkdir()
            (media / "AT_Icon_Decoration_Test.png").write_bytes(b"furniture")
            (media / "AT_Main_Avatar_Test.png").write_bytes(b"character")
            (media / "AT_Main_Avatar_Second.png").write_bytes(b"second")
            (media / "AT_Theme_Test.png").write_bytes(b"theme")
            (media / "AT_Stage_Music_Test.png").write_bytes(b"music")
            (media / "AT_Common_Icon_Star.png").write_bytes(b"buff")

            result = build_private_preview(
                master_root=FIXTURE_ROOT / "master",
                catalog_path=FIXTURE_ROOT / "catalog.json",
                media_root=media,
                output_root=root / "private-output",
                source_release_id="global-staging-fixture-media",
                site_root=REPO_ROOT / "site",
                build_site=False,
                generated_at="2026-08-05T00:00:00Z",
            )

            staged = json.loads(
                (result.public_root / "anontokyo-media.json").read_text()
            )
            self.assertEqual(
                {item["logicalKey"] for item in staged},
                {
                    "AT_Icon_Decoration_Test",
                    "AT_Main_Avatar_Test",
                    "AT_Main_Avatar_Second",
                    "AT_Theme_Test",
                    "AT_Stage_Music_Test",
                    "AT_Common_Icon_Star",
                },
            )
            self.assertEqual(result.staged_media_count, 6)
            self.assertEqual(result.staged_media_bytes, 38)


if __name__ == "__main__":
    unittest.main()
