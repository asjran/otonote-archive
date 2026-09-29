"""Map the validated ``full_songs_v1`` report to the existing music catalog.

The full-song pipeline writes a ``cri-media-report.json`` containing 33
``audio_split_acb`` records. Each Master music entry owns exactly one
CRI sound, cue sheet and bundle name; this module resolves that chain
and decides which tracks are eligible for site publication.

The adapter never touches Astro pages or generates media; the page
build embeds the resulting metadata and the build runner transcodes
the source FLAC to AAC/M4A.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


class MusicAudioError(ValueError):
    """Raised when the music audio mapping violates an invariant."""


REQUIRED_MASTER_TABLES = (
    "MasterLiveMusic",
    "MasterSound",
    "MasterSoundCueSheet",
)


@dataclass(frozen=True)
class AudioRecord:
    track_id: str
    cue_sheet_name: str
    flac_path: Path
    flac_sha256_prefix: str
    duration_seconds: float
    sample_rate: int
    channels: int
    flac_size: int

    @property
    def target_filename(self) -> str:
        return f"{self.track_id}-{self.flac_sha256_prefix}.m4a"

    @property
    def target_url(self) -> str:
        return f"/media/music/{self.target_filename}"

    def with_prefix(self, flac_sha256_prefix: str) -> "AudioRecord":
        return AudioRecord(
            track_id=self.track_id,
            cue_sheet_name=self.cue_sheet_name,
            flac_path=self.flac_path,
            flac_sha256_prefix=flac_sha256_prefix,
            duration_seconds=self.duration_seconds,
            sample_rate=self.sample_rate,
            channels=self.channels,
            flac_size=self.flac_size,
        )


@dataclass(frozen=True)
class AudioProjection:
    track_id: str
    cue_sheet_name: str
    duration_seconds: float
    audio_url: str
    audio_codec: str
    audio_status: str
    audio_playback: bool
    audio_download: bool

    def as_catalog_overlay(self) -> dict[str, Any]:
        return {
            "audioUrl": self.audio_url,
            "audioDuration": self.duration_seconds,
            "audioCodec": self.audio_codec,
            "audioStatus": self.audio_status,
            "audioPlayback": self.audio_playback,
            "audioDownload": self.audio_download,
        }


@dataclass(frozen=True)
class MusicAudioBuild:
    overlays: dict[str, dict[str, Any]]
    publish_records: list[AudioRecord]
    rejected: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_master_json(master_root: Path, table: str) -> list[dict[str, Any]]:
    path = master_root / f"{table}.json"
    if not path.is_file():
        raise MusicAudioError(f"missing master table: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise MusicAudioError(f"{table} must contain an _allData array")
    return rows


def _load_report(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise MusicAudioError(f"cri-media-report not found: {report_path}")
    with report_path.open("r", encoding="utf-8") as stream:
        try:
            return json.load(stream)
        except json.JSONDecodeError as exc:
            raise MusicAudioError(f"invalid JSON in {report_path}: {exc}") from exc


def _allowed_root(report_path: Path) -> Path:
    return report_path.resolve().parent


def _index_by(rows: Iterable[dict[str, Any]], field: str) -> dict[Any, dict[str, Any]]:
    index: dict[Any, dict[str, Any]] = {}
    for row in rows:
        index[row.get(field)] = row
    return index


def _short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _is_audio_publish_enabled() -> bool:
    flag = os.environ.get("OURNOTES_ENABLE_MUSIC_AUDIO", "").strip().lower()
    if flag in {"", "1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return True


def _select_eligible_record(report: dict[str, Any], cue: str) -> tuple[dict[str, Any] | None, str | None]:
    """Find the unique ``audio_split_acb`` record for ``cue`` or return a reason."""

    candidates = [
        entry
        for entry in report.get("files", [])
        if entry.get("kind") in {"audio_split_acb", "audio_unity_acb"}
        and entry.get("cue_sheet_name") == cue
    ]
    if len(candidates) == 0:
        return None, "missing_report_record"
    if len(candidates) > 1:
        return None, "duplicate_report_record"
    record = candidates[0]
    if not record.get("ok"):
        return None, "record_not_ok"
    streams = record.get("streams") or []
    if len(streams) != 1:
        return None, "stream_count_not_one"
    stream = streams[0]
    validation = stream.get("validation") or {}
    if not validation.get("ok"):
        return None, "stream_validation_failed"
    quality = (validation.get("quality") or {})
    if quality.get("status") != "audible":
        return None, "quality_not_audible"
    return record, None


def _flac_path_from_record(
    record: dict[str, Any],
    report_base: Path,
    repo_root: Path,
) -> Path | None:
    streams = record.get("streams") or []
    if not streams:
        return None
    output = streams[0].get("output")
    if not isinstance(output, str) or not output:
        return None
    path = Path(output)
    if path.is_absolute():
        return path.resolve()
    # Report paths were written relative to the repo root; they may also be
    # relative to the report output directory. Try repo-root first.
    candidate = (repo_root / path).resolve()
    if candidate.is_file():
        return candidate
    candidate = (report_base / path).resolve()
    if candidate.is_file():
        return candidate
    return (repo_root / path).resolve()


def _sha256_prefix(path: Path, length: int = 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def _probe_audio(ffprobe: Path, target: Path) -> dict[str, Any]:
    import json as _json
    import subprocess

    result = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MusicAudioError(
            f"ffprobe rejected {target}: {result.stderr[-500:]}"
        )
    return _json.loads(result.stdout)


def publish_music_audio(
    build: MusicAudioBuild,
    output_root: Path,
    *,
    ffmpeg: Path,
    ffprobe: Path,
    skip_media: bool = False,
) -> list[AudioRecord]:
    """Transcode each FLAC into the site media directory and prune stale files."""

    if not build.publish_records:
        # Nothing to publish; prune the directory to keep the artifact clean.
        if not skip_media:
            target_dir = output_root / "media" / "music"
            if target_dir.is_dir():
                for child in target_dir.iterdir():
                    if child.is_file():
                        child.unlink()
        return []

    target_dir = output_root / "media" / "music"
    published: list[AudioRecord] = []
    expected_names: set[str] = set()

    for entry in build.publish_records:
        flac_path = entry.flac_path
        flac_sha = _sha256_prefix(flac_path)
        record = entry.with_prefix(flac_sha)
        expected_names.add(record.target_filename)
        target = target_dir / record.target_filename
        from tools.conversion_cache import restore as cache_restore, save as cache_save
        from tools.global_remote_sync import file_hash
        source_sha = file_hash(flac_path)
        recipe = 'song-aac-160k-stereo-mp4-v1'
        if not skip_media:
            cache_restore(source_sha, recipe, target)

        if target.is_file() and not skip_media:
            try:
                _probe_audio(ffprobe, target)
                cache_save(source_sha, recipe, target)
                published.append(record)
                continue
            except MusicAudioError:
                target.unlink(missing_ok=True)

        if skip_media:
            published.append(record)
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_target = target_dir / f".{record.target_filename}.tmp"
        tmp_target.unlink(missing_ok=True)
        import subprocess

        result = subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-y",
                "-i",
                str(flac_path),
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(tmp_target),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            tmp_target.unlink(missing_ok=True)
            raise MusicAudioError(
                f"ffmpeg failed for {flac_path.name}: {result.stderr[-500:]}"
            )
        try:
            _probe_audio(ffprobe, tmp_target)
        except MusicAudioError as exc:
            tmp_target.unlink(missing_ok=True)
            raise MusicAudioError(
                f"transcoded {record.target_filename} failed validation: {exc}"
            ) from exc
        tmp_target.replace(target)
        cache_save(source_sha, recipe, target)
        published.append(record)

    if not skip_media:
        for child in target_dir.iterdir():
            if child.is_file() and child.name not in expected_names:
                child.unlink()

    return published


def build_music_audio(
    master_root: Path,
    report_path: Path,
    *,
    repo_root: Path | None = None,
    sound_field: str = "_musicSoundID",
) -> MusicAudioBuild:
    """Resolve every music track to a report record and produce site overlays."""

    music_rows = _load_master_json(master_root, "MasterLiveMusic")
    sound_rows = _load_master_json(master_root, "MasterSound")
    cuesheet_rows = _load_master_json(master_root, "MasterSoundCueSheet")
    report = _load_report(report_path)

    sound_idx = _index_by(sound_rows, "_id")
    cuesheet_idx = _index_by(cuesheet_rows, "_id")
    allowed_root = _allowed_root(report_path)
    repo_root_resolved = (
        repo_root.resolve() if repo_root else allowed_root
    )

    overlays: dict[str, dict[str, Any]] = {}
    publish_records: list[AudioRecord] = []
    rejected: list[dict[str, Any]] = []

    cue_to_tracks: dict[str, list[int]] = {}
    for track in music_rows:
        sid = track.get(sound_field)
        if not isinstance(sid, int):
            continue
        sound = sound_idx.get(sid)
        if sound is None:
            raise MusicAudioError(
                f"music track {track['_id']} references missing sound {sid}"
            )
        csid = sound.get("_soundCueSheetID")
        if not isinstance(csid, int):
            raise MusicAudioError(
                f"sound {sid} for music track {track['_id']} has invalid cue sheet"
            )
        cuesheet = cuesheet_idx.get(csid)
        if cuesheet is None:
            raise MusicAudioError(
                f"music track {track['_id']} references missing cue sheet {csid}"
            )
        cue_name = cuesheet.get("_cueSheetName")
        if not isinstance(cue_name, str) or not cue_name:
            raise MusicAudioError(
                f"cue sheet {csid} for music track {track['_id']} has no name"
            )
        if sound.get("_cueName") != cue_name:
            raise MusicAudioError(
                f"music track {track['_id']} sound cue name {sound.get('_cueName')!r} "
                f"does not match cue sheet {cue_name!r}"
            )
        cue_to_tracks.setdefault(cue_name, []).append(track["_id"])

    for cue, master_ids in cue_to_tracks.items():
        if len(master_ids) > 1:
            raise MusicAudioError(
                f"cue sheet {cue!r} is shared by music tracks {master_ids}"
            )
        track_master_id = master_ids[0]
        track_id = f"music-{track_master_id}"

        record, reason = _select_eligible_record(report, cue)
        if record is None:
            rejected.append({"trackId": track_id, "cue": cue, "reason": reason})
            continue

        flac_path = _flac_path_from_record(record, allowed_root, repo_root_resolved)
        if flac_path is None:
            rejected.append({"trackId": track_id, "cue": cue, "reason": "no_flac_path"})
            continue
        try:
            flac_path.relative_to(allowed_root)
        except ValueError:
            rejected.append(
                {"trackId": track_id, "cue": cue, "reason": "flac_outside_report_root"}
            )
            continue
        if not flac_path.is_file():
            rejected.append({"trackId": track_id, "cue": cue, "reason": "flac_missing"})
            continue

        stream = record["streams"][0]
        duration = float(stream.get("duration_seconds") or 0)
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
        flac_size = int(stream.get("size") or 0)
        if duration <= 0 or sample_rate <= 0 or channels <= 0 or flac_size <= 0:
            rejected.append(
                {"trackId": track_id, "cue": cue, "reason": "non_positive_metadata"}
            )
            continue

        publish_records.append(
            AudioRecord(
                track_id=track_id,
                cue_sheet_name=cue,
                flac_path=flac_path,
                flac_sha256_prefix="",
                duration_seconds=duration,
                sample_rate=sample_rate,
                channels=channels,
                flac_size=flac_size,
            )
        )

    if not _is_audio_publish_enabled():
        return MusicAudioBuild(
            overlays={},
            publish_records=[],
            rejected=[],
            warnings=["audio publish disabled via OURNOTES_ENABLE_MUSIC_AUDIO"],
        )

    if rejected:
        reasons = ", ".join(
            f"{item['trackId']} ({item['reason']})" for item in rejected
        )
        raise MusicAudioError(
            f"{len(rejected)} music track(s) cannot be published: {reasons}"
        )

    for record in publish_records:
        projection = AudioProjection(
            track_id=record.track_id,
            cue_sheet_name=record.cue_sheet_name,
            duration_seconds=record.duration_seconds,
            audio_url=record.target_url,
            audio_codec="aac",
            audio_status="available",
            audio_playback=True,
            audio_download=True,
        )
        overlays[record.track_id] = projection.as_catalog_overlay()

    return MusicAudioBuild(
        overlays=overlays,
        publish_records=publish_records,
        rejected=rejected,
        warnings=[],
    )
