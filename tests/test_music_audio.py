from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.music_audio import (
    MusicAudioError,
    AudioProjection,
    AudioRecord,
    MusicAudioBuild,
    _is_audio_publish_enabled,
    build_music_audio,
    publish_music_audio,
    _sha256_prefix,
)


def write_master(root: Path, tables: dict[str, list[dict[str, object]]]) -> None:
    for name, rows in tables.items():
        (root / f"{name}.json").write_text(
            json.dumps({"_allData": rows}, ensure_ascii=False),
            encoding="utf-8",
        )


def write_report(root: Path, files: list[dict[str, object]], output_dir: str) -> Path:
    path = root / "cri-media-report.json"
    path.write_text(
        json.dumps({"files": files, "output": output_dir}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _safe_flac_path(flac: Path) -> str:
    """Return a resolved FLAC path string for use in report records."""
    return str(flac.resolve())


def a_report_record(
    cue: str,
    *,
    ok: bool = True,
    stream_status: str = "audible",
    flac_path: str | None = None,
) -> dict[str, object]:
    return {
        "kind": "audio_split_acb",
        "cue_sheet_name": cue,
        "ok": ok,
        "streams": [
            {
                "output": flac_path,
                "duration_seconds": 120.0,
                "sample_rate": 48000,
                "channels": 2,
                "size": 15000000,
                "validation": {
                    "ok": True,
                    "quality": {"status": stream_status},
                },
            }
        ],
    }


class MusicAudioMappingTest(unittest.TestCase):
    def test_preview_uses_jingle_binding_and_embedded_acb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / 'master'
            master.mkdir()
            flac = root / 'preview.flac'
            flac.write_bytes(b'validated fixture')
            write_master(master, {
                'MasterLiveMusic': [{'_id': 100010, '_musicSoundID': 1, '_jingleSoundID': 2}],
                'MasterSound': [
                    {'_id': 1, '_soundCueSheetID': 10, '_cueName': 'M_Norosi'},
                    {'_id': 2, '_soundCueSheetID': 20, '_cueName': 'M_Norosi_short'},
                ],
                'MasterSoundCueSheet': [
                    {'_id': 10, '_cueSheetName': 'M_Norosi'},
                    {'_id': 20, '_cueSheetName': 'M_Norosi_short'},
                ],
            })
            record = a_report_record('M_Norosi_short', flac_path=str(flac))
            record['kind'] = 'audio_unity_acb'
            report = write_report(root, [record], str(root))
            result = build_music_audio(master, report, sound_field='_jingleSoundID')
            self.assertEqual(result.publish_records[0].cue_sheet_name, 'M_Norosi_short')
            self.assertTrue(result.overlays['music-100010']['audioDownload'])
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_all_tracks_map_to_unique_report_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            audio = root / "audio" / "M_Mayoiuta_test"
            audio.mkdir(parents=True)
            flac = audio / "001_M_Mayoiuta.flac"
            flac.write_bytes(b"dummy flac")

            write_master(
                master,
                {
                    "MasterLiveMusic": [
                        {
                            "_id": 100001,
                            "_musicSoundID": 1,
                            "_titleTextID": "t1",
                        },
                    ],
                    "MasterSound": [
                        {
                            "_id": 1,
                            "_soundCueSheetID": 100,
                            "_cueName": "M_Mayoiuta",
                        }
                    ],
                    "MasterSoundCueSheet": [
                        {"_id": 100, "_cueSheetName": "M_Mayoiuta"}
                    ],
                },
            )
            report = write_report(
                root,
                [
                    a_report_record(
                        "M_Mayoiuta",
                        flac_path=str(flac),
                    ),
                ],
                str(root),
            )

            build = build_music_audio(master, report, repo_root=root)
            self.assertEqual(len(build.overlays), 1)
            overlay = build.overlays["music-100001"]
            self.assertEqual(overlay["audioStatus"], "available")
            self.assertEqual(overlay["audioCodec"], "aac")
            self.assertTrue(overlay["audioPlayback"])
            self.assertTrue(overlay["audioDownload"])

    def test_rejects_missing_sound_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            write_master(
                master,
                {
                    "MasterLiveMusic": [
                        {
                            "_id": 100001,
                            "_musicSoundID": 99999,
                            "_titleTextID": "t1",
                        },
                    ],
                    "MasterSound": [],
                    "MasterSoundCueSheet": [],
                },
            )
            report = write_report(root, [], str(root))
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_rejects_cue_name_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            write_master(
                master,
                {
                    "MasterLiveMusic": [
                        {
                            "_id": 100001,
                            "_musicSoundID": 1,
                            "_titleTextID": "t1",
                        },
                    ],
                    "MasterSound": [
                        {
                            "_id": 1,
                            "_soundCueSheetID": 100,
                            "_cueName": "WrongName",
                        }
                    ],
                    "MasterSoundCueSheet": [
                        {"_id": 100, "_cueSheetName": "CorrectName"},
                    ],
                },
            )
            report = write_report(root, [], str(root))
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_rejects_duplicate_cue_across_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            write_master(
                master,
                {
                    "MasterLiveMusic": [
                        {
                            "_id": 100001,
                            "_musicSoundID": 1,
                            "_titleTextID": "t1",
                        },
                        {
                            "_id": 100002,
                            "_musicSoundID": 2,
                            "_titleTextID": "t2",
                        },
                    ],
                    "MasterSound": [
                        {
                            "_id": 1,
                            "_soundCueSheetID": 100,
                            "_cueName": "SharedCue",
                        },
                        {
                            "_id": 2,
                            "_soundCueSheetID": 100,
                            "_cueName": "SharedCue",
                        },
                    ],
                    "MasterSoundCueSheet": [
                        {"_id": 100, "_cueSheetName": "SharedCue"},
                    ],
                },
            )
            report = write_report(root, [], str(root))
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_fails_on_missing_report_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            write_master(
                master,
                {
                    "MasterLiveMusic": [
                        {
                            "_id": 100001,
                            "_musicSoundID": 1,
                            "_titleTextID": "t1",
                        },
                    ],
                    "MasterSound": [
                        {
                            "_id": 1,
                            "_soundCueSheetID": 100,
                            "_cueName": "NoReportMatch",
                        }
                    ],
                    "MasterSoundCueSheet": [
                        {"_id": 100, "_cueSheetName": "NoReportMatch"},
                    ],
                },
            )
            report = write_report(root, [], str(root))
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_fails_when_32_of_33_reports_available(self) -> None:
        """Design: 33/33 must succeed or build fails."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            flac_dir = root / "audio" / "test"
            flac_dir.mkdir(parents=True)
            flac = flac_dir / "test.flac"
            flac.write_bytes(b"dummy flac")

            music_rows = []
            sound_rows = []
            cuesheet_rows = []
            report_rows = []
            for i in range(1, 34):
                music_rows.append(
                    {"_id": 100000 + i, "_musicSoundID": i, "_titleTextID": f"t{i}"}
                )
                cue = f"Song_{i}"
                sound_rows.append(
                    {
                        "_id": i,
                        "_soundCueSheetID": 100 + i,
                        "_cueName": cue,
                    }
                )
                cuesheet_rows.append(
                    {"_id": 100 + i, "_cueSheetName": cue}
                )
                if i <= 32:
                    # Only provide 32 of 33 report records → should fail
                    report_rows.append(
                        a_report_record(cue, flac_path=str(flac))
                    )

            write_master(
                master,
                {
                    "MasterLiveMusic": music_rows,
                    "MasterSound": sound_rows,
                    "MasterSoundCueSheet": cuesheet_rows,
                },
            )
            report = write_report(root, report_rows, str(root))
            with self.assertRaises(MusicAudioError):
                build_music_audio(master, report)

    def test_33_of_33_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master"
            master.mkdir()
            flac_dir = root / "audio" / "test"
            flac_dir.mkdir(parents=True)
            flac = flac_dir / "test.flac"
            flac.write_bytes(b"dummy flac")

            music_rows = []
            sound_rows = []
            cuesheet_rows = []
            report_rows = []
            for i in range(1, 34):
                music_rows.append(
                    {"_id": 100000 + i, "_musicSoundID": i, "_titleTextID": f"t{i}"}
                )
                cue = f"Song_{i}"
                sound_rows.append(
                    {"_id": i, "_soundCueSheetID": 100 + i, "_cueName": cue}
                )
                cuesheet_rows.append(
                    {"_id": 100 + i, "_cueSheetName": cue}
                )
                report_rows.append(
                    a_report_record(cue, flac_path=str(flac))
                )

            write_master(
                master,
                {
                    "MasterLiveMusic": music_rows,
                    "MasterSound": sound_rows,
                    "MasterSoundCueSheet": cuesheet_rows,
                },
            )
            report = write_report(root, report_rows, str(root))
            build = build_music_audio(master, report, repo_root=root)
            self.assertEqual(len(build.overlays), 33)
            self.assertEqual(len(build.publish_records), 33)
            self.assertEqual(len(build.rejected), 0)


class AudioPublishTest(unittest.TestCase):
    def test_sha256_prefix_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flac = root / "test.flac"
            flac.write_bytes(b"deterministic-content")
            prefix = _sha256_prefix(flac)
            self.assertEqual(len(prefix), 16)
            # Same content → same prefix (deterministic naming)
            flac2 = root / "test2.flac"
            flac2.write_bytes(b"deterministic-content")
            self.assertEqual(_sha256_prefix(flac2), prefix)
            # Different content → different prefix
            flac3 = root / "test3.flac"
            flac3.write_bytes(b"different-content")
            self.assertNotEqual(_sha256_prefix(flac3), prefix)

    def test_skip_media_prunes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            music_dir = output / "media" / "music"
            music_dir.mkdir(parents=True)
            (music_dir / "stale.m4a").write_text("stale")

            ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
            ffprobe = Path("/opt/homebrew/bin/ffprobe")

            build = MusicAudioBuild(
                overlays={}, publish_records=[], rejected=[], warnings=[]
            )
            published = publish_music_audio(
                build, output, ffmpeg=ffmpeg, ffprobe=ffprobe
            )
            self.assertEqual(len(published), 0)
            self.assertFalse((music_dir / "stale.m4a").exists())


class EnvVarTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("OURNOTES_ENABLE_MUSIC_AUDIO", None)

    def tearDown(self) -> None:
        if self._saved is not None:
            os.environ["OURNOTES_ENABLE_MUSIC_AUDIO"] = self._saved

    def test_default_is_enabled(self) -> None:
        self.assertTrue(_is_audio_publish_enabled())

    def test_explicit_off_disables(self) -> None:
        with patch.dict(os.environ, {"OURNOTES_ENABLE_MUSIC_AUDIO": "off"}):
            self.assertFalse(_is_audio_publish_enabled())

    def test_zero_disables(self) -> None:
        with patch.dict(os.environ, {"OURNOTES_ENABLE_MUSIC_AUDIO": "0"}):
            self.assertFalse(_is_audio_publish_enabled())


if __name__ == "__main__":
    unittest.main()
