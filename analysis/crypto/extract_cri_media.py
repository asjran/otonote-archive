#!/usr/bin/env python3
"""Decrypt CRI ACB/HCA audio and USM video from the extracted Android files."""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR.parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from wannacri.usm import OpMode, Usm
except ImportError as error:
    raise SystemExit(
        "WannaCRI is required. Install analysis dependencies with:\n"
        "python3 -m pip install --target analysis/vendor "
        "-r analysis/requirements.txt"
    ) from error


CURRENT_USM_KEY = int(os.environ.get("OURNOTES_CRI_KEY", "0"), 0)
HASH_SUFFIX = re.compile(r"_[0-9a-f]{32}$", re.IGNORECASE)
INVALID_FILENAME = re.compile(r"[^0-9A-Za-z._-]+")
AUDIO_QUALITY_METRICS = (
    "Peak level dB",
    "RMS level dB",
    "Peak count",
    "Entropy",
    "Number of samples",
)


def find_executable(explicit: Optional[Path], candidates: Iterable[str]) -> Path:
    if explicit:
        if explicit.is_file():
            return explicit
        raise FileNotFoundError(explicit)

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved)
        path = Path(candidate)
        if path.is_file():
            return path
    raise FileNotFoundError(f"executable not found: {', '.join(candidates)}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class MediaError(RuntimeError):
    """Raised when media extraction cannot proceed."""


def clean_name(path: Path) -> str:
    name = path.name
    if path.suffix.lower() in (".acb", ".awb", ".usm"):
        name = path.stem
    name = HASH_SUFFIX.sub("", name)
    name = INVALID_FILENAME.sub("_", name).strip("._")
    return name or path.parent.name or "unnamed"


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def resolve_hca_key(usm_key: int, explicit_hca_key: Optional[int]) -> int:
    """Return the external CRI key expected by vgmstream."""

    return usm_key if explicit_hca_key is None else explicit_hca_key


def parse_audio_quality(output: str) -> dict[str, Any]:
    """Parse FFmpeg astats output and flag characteristic bad-key audio."""

    values: dict[str, float] = {}
    for raw_line in output.splitlines():
        line = raw_line.split("] ", 1)[-1].strip()
        for metric in AUDIO_QUALITY_METRICS:
            prefix = f"{metric}:"
            if not line.startswith(prefix):
                continue
            raw_value = line[len(prefix) :].strip()
            try:
                values[metric] = float(raw_value)
            except ValueError:
                pass
            break

    required = set(AUDIO_QUALITY_METRICS)
    if set(values) != required:
        return {
            "ok": False,
            "status": "unavailable",
            "reason": "FFmpeg astats did not emit all required metrics",
        }

    peak_level = values["Peak level dB"]
    rms_level = values["RMS level dB"]
    peak_count = values["Peak count"]
    entropy = values["Entropy"]
    number_of_samples = int(values["Number of samples"])
    peak_ratio = (
        peak_count / number_of_samples if number_of_samples > 0 else math.inf
    )
    silent = (
        math.isinf(rms_level)
        and rms_level < 0
        or (
            entropy == 0
            and (math.isinf(peak_level) or peak_level <= -120)
        )
    )
    suspicious = (
        not silent
        and math.isfinite(peak_level)
        and peak_level >= -0.1
        and entropy < 0.2
        and peak_count >= 32
        and peak_ratio >= 0.001
    )
    status = (
        "silent"
        if silent
        else "suspicious_decryption"
        if suspicious
        else "audible"
    )
    return {
        "ok": not suspicious,
        "status": status,
        "peak_level_db": peak_level,
        "rms_level_db": rms_level,
        "peak_count": peak_count,
        "entropy": entropy,
        "number_of_samples": number_of_samples,
        "peak_ratio": peak_ratio,
    }


def validate_media(
    ffmpeg: Path,
    path: Path,
    stream_selector: str,
    *,
    analyze_audio: bool = False,
) -> dict[str, Any]:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-v",
        "info" if analyze_audio else "error",
        "-i",
        str(path),
        "-map",
        stream_selector,
    ]
    if analyze_audio:
        command.extend(["-af", "astats=metadata=0:reset=0"])
    command.extend(["-f", "null", "-"])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    quality = parse_audio_quality(result.stderr) if analyze_audio else None
    structural_ok = result.returncode == 0
    validation = {
        "ok": structural_ok and (quality is None or quality["ok"]),
        "structural_ok": structural_ok,
        "return_code": result.returncode,
        "warnings": (
            [line for line in result.stderr.splitlines() if line.strip()][-10:]
            if not structural_ok
            else []
        ),
    }
    if quality is not None:
        validation["quality"] = quality
    return validation


def decode_flac(
    vgmstream: Path,
    ffmpeg: Path,
    source: Path,
    subsong: int,
    output: Path,
) -> None:
    temporary_wav = source.parent / f"subsong_{subsong:04d}.wav"
    decoder = subprocess.run(
        [
            str(vgmstream),
            "-i",
            "-s",
            str(subsong),
            "-o",
            str(temporary_wav),
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    decoder_log = decoder.stdout + decoder.stderr
    if decoder.returncode != 0 or "decryption key not found" in decoder_log:
        raise RuntimeError(
            f"vgmstream failed ({decoder.returncode}): {decoder_log[-1000:]}"
        )
    encoder = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-y",
            "-i",
            str(temporary_wav),
            "-c:a",
            "flac",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    temporary_wav.unlink(missing_ok=True)
    if encoder.returncode != 0:
        raise RuntimeError(
            f"FLAC encode failed ({encoder.returncode}): {encoder.stderr[-1000:]}"
        )


def process_acb(
    source: Path,
    digest: str,
    output_root: Path,
    work_root: Path,
    hca_key: int,
    vgmstream: Path,
    ffmpeg: Path,
) -> dict[str, Any]:
    display_name = clean_name(source)
    base_name = f"{display_name}_{digest[:8]}"
    work_dir = work_root / base_name
    output_dir = output_root / "audio" / base_name
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    acb = work_dir / f"{base_name}.acb"
    shutil.copyfile(source, acb)
    key_bytes = str(hca_key).encode("ascii")
    Path(str(acb) + "key").write_bytes(key_bytes)
    acb.with_suffix(".hcakey").write_bytes(key_bytes)
    (work_dir / ".acbkey").write_bytes(key_bytes)
    (work_dir / ".hcakey").write_bytes(key_bytes)

    decode_source = acb
    source_format = "acb"
    try:
        first_info = run_json(
            [str(vgmstream), "-m", "-I", "-s", "1", str(decode_source)]
        )
    except subprocess.CalledProcessError:
        data = acb.read_bytes()
        afs2_offset = data.find(b"AFS2")
        if afs2_offset < 0:
            raise
        decode_source = work_dir / f"{base_name}.awb"
        decode_source.write_bytes(data[afs2_offset:])
        Path(str(decode_source) + "key").write_bytes(key_bytes)
        (work_dir / ".awbkey").write_bytes(key_bytes)
        source_format = "embedded_awb_fallback"
        first_info = run_json(
            [str(vgmstream), "-m", "-I", "-s", "1", str(decode_source)]
        )

    stream_total = int(first_info.get("streamInfo", {}).get("total") or 1)
    streams = []
    for subsong in range(1, stream_total + 1):
        try:
            info = (
                first_info
                if subsong == 1
                else run_json(
                    [
                        str(vgmstream),
                        "-m",
                        "-I",
                        "-s",
                        str(subsong),
                        str(decode_source),
                    ]
                )
            )
        except subprocess.CalledProcessError:
            continue
        stream_name = info.get("streamInfo", {}).get("name")
        safe_stream_name = INVALID_FILENAME.sub("_", stream_name or "").strip("._")
        suffix = f"_{safe_stream_name}" if safe_stream_name else ""
        output = output_dir / f"{subsong:03d}{suffix}.flac"
        decode_flac(vgmstream, ffmpeg, decode_source, subsong, output)
        validation = validate_media(
            ffmpeg,
            output,
            "0:a:0",
            analyze_audio=True,
        )
        streams.append(
            {
                "subsong": subsong,
                "name": stream_name,
                "encoding": info.get("encoding"),
                "sample_rate": info.get("sampleRate"),
                "channels": info.get("channels"),
                "samples": info.get("numberOfSamples"),
                "duration_seconds": (
                    info.get("numberOfSamples", 0) / info.get("sampleRate", 1)
                ),
                "output": str(output),
                "size": output.stat().st_size,
                "validation": validation,
            }
        )

    result = {
        "kind": "audio_acb",
        "source": str(source),
        "sha256": digest,
        "hca_key": hca_key,
        "source_format": source_format,
        "declared_stream_slots": stream_total,
        "decoded_streams": len(streams),
        "streams": streams,
        "ok": bool(streams)
        and all(stream["validation"]["ok"] for stream in streams),
    }
    if result["ok"]:
        shutil.rmtree(work_dir)
    return result


def write_usm_streams(
    source: Path, output_dir: Path, usm_key: int, ffprobe: Path
) -> tuple[list[Path], list[Path]]:
    usm = Usm.open(source, key=usm_key)
    videos = []
    audios = []

    for index, item in enumerate(usm.videos):
        output = output_dir / f"video_{index:02d}.bin"
        with output.open("wb") as stream:
            for packet, _ in item.stream(OpMode.DECRYPT, usm.video_key):
                stream.write(packet)
        codec_result = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        codec = codec_result.stdout.strip()
        extension = {
            "vp9": ".ivf",
            "h264": ".h264",
            "mpeg1video": ".mpg",
            "mpeg2video": ".mpg",
        }.get(codec, ".video")
        renamed = output.with_suffix(extension)
        output.rename(renamed)
        videos.append(renamed)

    for index, item in enumerate(usm.audios):
        output = output_dir / f"audio_{index:02d}.bin"
        with output.open("wb") as stream:
            for packet in item.stream(OpMode.DECRYPT, usm.audio_key):
                stream.write(packet)
        magic = output.read_bytes()[:4]
        if magic[:3] in (b"HCA", bytes((0xC8, 0xC3, 0xC1))):
            renamed = output.with_suffix(".hca")
        elif magic[:2] == b"\x80\x00":
            renamed = output.with_suffix(".adx")
        else:
            renamed = output
        output.rename(renamed)
        audios.append(renamed)

    return videos, audios


def create_site_media(
    ffmpeg: Path, videos: list[Path], audios: list[Path], output_base: Path
) -> Path:
    is_vp9 = videos[0].suffix == ".ivf"
    is_h264 = videos[0].suffix == ".h264"
    output = output_base.with_suffix(".webm" if is_vp9 else ".mp4")
    command = [str(ffmpeg), "-v", "error", "-y", "-i", str(videos[0])]
    if audios:
        command.extend(["-i", str(audios[0])])
    command.extend(["-map", "0:v:0"])
    if audios:
        command.extend(["-map", "1:a:0"])
    if is_vp9 or is_h264:
        command.extend(["-c:v", "copy"])
    else:
        command.extend(
            ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
        )
    if audios:
        if is_vp9:
            command.extend(["-c:a", "libopus", "-b:a", "160k"])
        else:
            command.extend(["-c:a", "aac", "-b:a", "192k"])
        command.append("-shortest")
    command.append(str(output))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"site media mux failed: {result.stderr[-1500:]}")
    return output


def probe_media(ffprobe: Path, path: Path) -> dict[str, Any]:
    return run_json(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,pix_fmt,sample_rate,channels,duration,nb_frames",
            "-show_entries",
            "format=format_name,duration,size",
            "-of",
            "json",
            str(path),
        ]
    )


def process_usm(
    source: Path,
    digest: str,
    output_root: Path,
    usm_key: int,
    ffmpeg: Path,
    ffprobe: Path,
) -> dict[str, Any]:
    display_name = clean_name(source)
    base_name = f"{display_name}_{digest[:8]}"
    output_dir = output_root / "video" / base_name
    output_dir.mkdir(parents=True, exist_ok=True)
    videos, audios = write_usm_streams(source, output_dir, usm_key, ffprobe)
    if not videos:
        raise RuntimeError("USM has no video stream")

    stream_validation = []
    for path in videos + audios:
        is_audio = path in audios
        stream_validation.append(
            {
                "path": str(path),
                "validation": validate_media(
                    ffmpeg,
                    path,
                    "0:a:0" if is_audio else "0:v:0",
                    analyze_audio=is_audio,
                ),
            }
        )
    audio_quality_statuses = [
        item["validation"].get("quality", {}).get("status")
        for item in stream_validation
        if Path(item["path"]) in audios
    ]
    if not audios:
        audio_status = "no_audio_stream"
    elif audio_quality_statuses and all(
        status == "silent" for status in audio_quality_statuses
    ):
        audio_status = "silent_audio_stream"
    elif any(status == "audible" for status in audio_quality_statuses):
        audio_status = "audible_audio_stream"
    else:
        audio_status = "audio_quality_failed"
    site_media = create_site_media(
        ffmpeg, videos, audios, output_dir / base_name
    )
    site_media_validation = validate_media(ffmpeg, site_media, "0:v:0")

    return {
        "kind": "video_usm",
        "source": str(source),
        "sha256": digest,
        "usm_key": usm_key,
        "video_streams": [str(path) for path in videos],
        "audio_streams": [str(path) for path in audios],
        "audio_status": audio_status,
        "site_media": str(site_media),
        "probe": probe_media(ffprobe, site_media),
        "stream_validation": stream_validation,
        "site_media_validation": site_media_validation,
        "ok": site_media_validation["ok"]
        and all(item["validation"]["ok"] for item in stream_validation),
    }


def discover(inputs: list[Path], output: Path) -> list[tuple[str, Path, str]]:
    seen: dict[str, Path] = {}
    media = []
    output_resolved = output.resolve()
    for root in inputs:
        if not root.exists():
            continue
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            try:
                if path.resolve().is_relative_to(output_resolved):
                    continue
            except AttributeError:
                if str(path.resolve()).startswith(str(output_resolved)):
                    continue
            with path.open("rb") as stream:
                magic = stream.read(4)
                if magic == b"@UTF":
                    has_afs2 = b"AFS2" in stream.read()
                    kind = "audio_acb" if has_afs2 else "utf_other"
                elif magic == b"CRID":
                    kind = "video_usm"
                else:
                    continue
            digest = sha256_file(path)
            if digest in seen:
                media.append(("duplicate", path, digest))
                continue
            seen[digest] = path
            media.append((kind, path, digest))
    return media


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decrypt CRI ACB/HCA audio and USM video."
    )
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        dest="inputs",
        required=True,
        help="input directory; repeat for multiple roots",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--usm-key",
        type=lambda value: int(value, 0),
        default=CURRENT_USM_KEY,
        help="package USM key as decimal or 0x-prefixed integer",
    )
    parser.add_argument(
        "--hca-key",
        type=lambda value: int(value, 0),
        help="HCA key override; defaults to the raw USM/CRI key",
    )
    parser.add_argument("--vgmstream", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--bundles",
        type=Path,
        help=(
            "directory containing UnityFS SplitAcbData bundles; when set, "
            "each bundle is reassembled and decoded alongside the ACB/USM run"
        ),
    )
    parser.add_argument(
        "--bundles-output",
        type=Path,
        help="output directory for bundle results (defaults to --output)",
    )
    args = parser.parse_args()

    if args.inputs:
        inputs = args.inputs
        missing_inputs = [path for path in inputs if not path.exists()]
        if missing_inputs:
            parser.error(
                "input path does not exist: "
                + ", ".join(str(path) for path in missing_inputs)
            )
    hca_key = resolve_hca_key(args.usm_key, args.hca_key)
    vgmstream = find_executable(
        args.vgmstream,
        ("vgmstream-cli", "/opt/homebrew/opt/vgmstream/bin/vgmstream-cli"),
    )
    ffmpeg = find_executable(
        args.ffmpeg, ("ffmpeg", "/opt/homebrew/opt/ffmpeg/bin/ffmpeg")
    )
    ffprobe = find_executable(
        args.ffprobe, ("ffprobe", "/opt/homebrew/opt/ffmpeg/bin/ffprobe")
    )
    args.output.mkdir(parents=True, exist_ok=True)
    work_root = args.output / "_work"
    work_root.mkdir(exist_ok=True)

    report: dict[str, Any] = {
        "inputs": [str(path) for path in inputs],
        "output": str(args.output),
        "keys": {
            "usm_key": args.usm_key,
            "usm_key_hex": f"0x{args.usm_key:016X}",
            "hca_key": hca_key,
            "hca_key_hex": f"0x{hca_key:016X}",
        },
        "files": [],
    }

    discovered = discover(inputs, args.output)
    if not discovered:
        parser.error("no CRI @UTF/CRID media files found in the input paths")

    for kind, source, digest in discovered:
        print(f"[{kind}] {source}", flush=True)
        if kind in ("duplicate", "utf_other"):
            report["files"].append(
                {
                    "kind": kind,
                    "source": str(source),
                    "sha256": digest,
                    "ok": True,
                }
            )
            continue
        try:
            if kind == "audio_acb":
                result = process_acb(
                    source,
                    digest,
                    args.output,
                    work_root,
                    hca_key,
                    vgmstream,
                    ffmpeg,
                )
            else:
                result = process_usm(
                    source,
                    digest,
                    args.output,
                    args.usm_key,
                    ffmpeg,
                    ffprobe,
                )
        except Exception as error:
            result = {
                "kind": kind,
                "source": str(source),
                "sha256": digest,
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }
            print(f"  ERROR: {result['error']}", file=sys.stderr, flush=True)
        report["files"].append(result)

    if args.bundles:
        try:
            from extract_split_acb import (
                discover_split_acb,
                process_split_acb,
                ReassemblyError,
            )
        except Exception as import_error:
            print(
                f"ERROR: could not import extract_split_acb: {import_error}",
                file=sys.stderr,
                flush=True,
            )
        else:
            bundles_output = args.bundles_output or args.output
            bundles_output.mkdir(parents=True, exist_ok=True)
            bundle_work_root = bundles_output / "_work"
            bundle_work_root.mkdir(exist_ok=True)
            candidates = discover_split_acb(args.bundles)
            for candidate in candidates:
                print(f"[audio_split_acb] {candidate.source}", flush=True)
                try:
                    bundle_result = process_split_acb(
                        candidate,
                        bundles_output,
                        bundle_work_root,
                        hca_key,
                        vgmstream,
                        ffmpeg,
                        process_acb,
                    )
                except Exception as error:
                    bundle_result = {
                        "kind": "audio_split_acb",
                        "source": str(candidate.source),
                        "sha256": candidate.sha256,
                        "cue_sheet_name": candidate.cue_sheet,
                        "ok": False,
                        "error": {
                            "stage": "process",
                            "message": f"{type(error).__name__}: {error}",
                        },
                    }
                    print(
                        f"  ERROR: {bundle_result['error']['message']}",
                        file=sys.stderr,
                        flush=True,
                    )
                report["files"].append(bundle_result)

        try:
            from extract_unity_acb import discover_unity_acb, process_unity_acb
        except Exception as import_error:
            print(
                f"ERROR: could not import extract_unity_acb: {import_error}",
                file=sys.stderr,
                flush=True,
            )
        else:
            bundles_output = args.bundles_output or args.output
            bundle_work_root = bundles_output / "_work"
            for candidate in discover_unity_acb(args.bundles):
                print(f"[audio_unity_acb] {candidate.source}", flush=True)
                report["files"].append(
                    process_unity_acb(
                        candidate,
                        bundles_output,
                        bundle_work_root,
                        hca_key,
                        vgmstream,
                        ffmpeg,
                        process_acb,
                    )
                )

    report["summary"] = {
        "total": len(report["files"]),
        "audio": sum(item["kind"] == "audio_acb" for item in report["files"]),
        "audio_split_acb": sum(
            item["kind"] == "audio_split_acb" for item in report["files"]
        ),
        "audio_unity_acb": sum(
            item["kind"] == "audio_unity_acb" for item in report["files"]
        ),
        "video": sum(item["kind"] == "video_usm" for item in report["files"]),
        "duplicates": sum(item["kind"] == "duplicate" for item in report["files"]),
        "other_utf": sum(item["kind"] == "utf_other" for item in report["files"]),
        "failed": sum(not item["ok"] for item in report["files"]),
    }
    report_path = args.report or args.output / "cri-media-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    print(f"report: {report_path}", flush=True)
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
