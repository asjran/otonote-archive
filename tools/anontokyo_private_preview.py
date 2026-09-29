#!/usr/bin/env python3
"""Build and serve the opt-in local AnonTokyo guide preview."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.anontokyo_projection import (  # noqa: E402
    AnonTokyoProjectionError,
    build_anontokyo_projection,
)
from tools.anontokyo_player_guide import (  # noqa: E402
    AnonTokyoPlayerGuideError,
    build_anontokyo_player_guide,
)


DEFAULT_SITE_ROOT = REPO_ROOT / "site"
CURRENT_GLOBAL_BASELINE = {
    "goods": 54,
    "decorations": 168,
    "storeLevels": 9,
    "tasks": 230,
    "taskTypes": 27,
    "characters": 10,
}
MAX_STAGED_MEDIA_FILES = 300
MAX_STAGED_MEDIA_BYTES = 32 * 1024 * 1024


class AnonTokyoPrivatePreviewError(RuntimeError):
    """Raised when an isolated private preview cannot be prepared."""


@dataclass(frozen=True)
class PrivatePreviewResult:
    release_root: Path
    projection_root: Path
    player_guide_root: Path
    public_root: Path
    dist_root: Path
    acceptance_path: Path
    record_counts: Mapping[str, int]
    staged_media_count: int
    staged_media_bytes: int


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.next")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _media_name(path: Path) -> str:
    return re.sub(r"^-?\d+_", "", path.stem).casefold()


_LOCALE_SUFFIX_RE = re.compile(r"\((?:en|ja|ko|zh-[A-Za-z]+)\)$", re.IGNORECASE)


def _media_index(media_root: Path) -> dict[str, Path]:
    if not media_root.is_dir():
        raise AnonTokyoPrivatePreviewError("media root is missing")
    candidates = sorted(
        media_root.rglob("*.png"),
        key=lambda path: ("/sprites/" not in path.as_posix(), path.as_posix()),
    )
    result: dict[str, Path] = {}
    for path in candidates:
        result.setdefault(_media_name(path), path)
    clean_entries: dict[str, Path] = {}
    for name, path in result.items():
        clean = _LOCALE_SUFFIX_RE.sub("", name)
        if clean != name and clean not in result:
            clean_entries[clean] = path
    result.update(clean_entries)
    return result


def _stage_media(
    projection_root: Path,
    player_guide_root: Path,
    public_root: Path,
    media_root: Path | None,
) -> tuple[list[dict[str, str]], int]:
    if media_root is None:
        return [], 0
    try:
        manifest = json.loads(
            (projection_root / "media-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AnonTokyoPrivatePreviewError("media projection is unreadable") from exc
    referenced_keys: set[str] = set()

    def collect(value: Any, *, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, key=child_key)
        elif isinstance(value, list):
            for child in value:
                collect(child, key=key)
        elif key == "imageKey" and isinstance(value, str) and value:
            referenced_keys.add(value)

    for name in (
        "store.json",
        "growth.json",
        "goods.json",
        "customers.json",
        "wardrobe.json",
        "inspiration.json",
        "furniture.json",
        "themes.json",
        "stages.json",
        "chats.json",
        "tasks.json",
        "staff.json",
        "guide.json",
        "mechanics.json",
        "studio.json",
    ):
        path = player_guide_root / name
        if name == "studio.json" and not path.is_file():
            continue
        try:
            collect(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnonTokyoPrivatePreviewError("player media references are unreadable") from exc

    projection_media = {
        str(record.get("logicalKey")): record
        for record in manifest.get("records", [])
        if isinstance(record, dict) and record.get("logicalKey")
    }
    index = _media_index(media_root)
    destination_root = public_root / "media/anontokyo"
    staged = []
    total_bytes = 0
    for logical_key in sorted(referenced_keys):
        record = projection_media.get(logical_key)
        if record is None:
            continue
        source = index.get(logical_key.casefold())
        if source is None:
            continue
        source_bytes = source.stat().st_size
        if len(staged) + 1 > MAX_STAGED_MEDIA_FILES:
            raise AnonTokyoPrivatePreviewError("player media file budget exceeded")
        if total_bytes + source_bytes > MAX_STAGED_MEDIA_BYTES:
            raise AnonTokyoPrivatePreviewError("player media byte budget exceeded")
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / f"{record['id']}.png"
        shutil.copy2(source, destination)
        total_bytes += source_bytes
        staged.append(
            {
                "id": str(record["id"]),
                "logicalKey": logical_key,
                "publicUrl": str(record["previewUrl"]),
            }
        )
    return staged, total_bytes


def _stage_audio(
    audio_manifest_path: Path | None,
    public_root: Path,
    *,
    staged_count: int,
    staged_bytes: int,
) -> tuple[list[dict[str, Any]], int]:
    if audio_manifest_path is None:
        return [], 0
    try:
        manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnonTokyoPrivatePreviewError("audio manifest is unreadable") from exc
    tracks = manifest.get("tracks") if isinstance(manifest, dict) else None
    if manifest.get("schemaVersion") != 1 or not isinstance(tracks, list):
        raise AnonTokyoPrivatePreviewError("audio manifest contract is invalid")

    destination_root = public_root / "media/anontokyo"
    staged: list[dict[str, Any]] = []
    added_bytes = 0
    logical_keys: set[str] = set()
    for track in tracks:
        if not isinstance(track, dict):
            raise AnonTokyoPrivatePreviewError("audio track contract is invalid")
        logical_key = track.get("logicalKey")
        file_name = track.get("file")
        expected_hash = track.get("sha256")
        duration = track.get("durationSeconds")
        if (
            not isinstance(logical_key, str)
            or not logical_key
            or logical_key in logical_keys
            or not isinstance(file_name, str)
            or Path(file_name).name != file_name
            or not file_name.lower().endswith(".mp3")
            or not isinstance(expected_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or not isinstance(duration, (int, float))
            or duration <= 0
            or track.get("quality") != "passed"
        ):
            raise AnonTokyoPrivatePreviewError("audio track contract is invalid")
        logical_keys.add(logical_key)
        source = audio_manifest_path.parent / file_name
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise AnonTokyoPrivatePreviewError("audio track is unreadable") from exc
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise AnonTokyoPrivatePreviewError("audio track hash mismatch")
        if staged_count + len(staged) + 1 > MAX_STAGED_MEDIA_FILES:
            raise AnonTokyoPrivatePreviewError("player media file budget exceeded")
        if staged_bytes + added_bytes + len(data) > MAX_STAGED_MEDIA_BYTES:
            raise AnonTokyoPrivatePreviewError("player media byte budget exceeded")

        media_id = hashlib.sha256(
            f"audio:{logical_key}:{expected_hash}".encode("utf-8")
        ).hexdigest()[:16]
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / f"{media_id}.mp3"
        shutil.copy2(source, destination)
        added_bytes += len(data)
        staged.append(
            {
                "id": media_id,
                "logicalKey": logical_key,
                "publicUrl": f"/media/anontokyo/{media_id}.mp3",
                "kind": "audio",
                "title": str(track.get("title") or logical_key),
                "durationSeconds": duration,
                "sha256": expected_hash,
            }
        )
    return staged, added_bytes


def _node_version(npm: Path) -> tuple[int, ...]:
    try:
        output = subprocess.run(
            [str(npm.parent / "node"), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return tuple(int(part) for part in output.removeprefix("v").split("."))
    except (OSError, subprocess.SubprocessError, ValueError):
        return ()


def _find_npm() -> Path:
    candidates: list[Path] = []
    resolved = shutil.which("npm")
    if resolved:
        candidates.append(Path(resolved))
    candidates.extend(Path.home().glob(".nvm/versions/node/v*/bin/npm"))
    supported = [candidate for candidate in candidates if _node_version(candidate) >= (22, 12)]
    if not supported:
        raise AnonTokyoPrivatePreviewError("Node.js 22.12 or newer is required")
    return max(supported, key=_node_version)


def _build_astro(
    *,
    site_root: Path,
    player_guide_root: Path,
    public_root: Path,
    dist_root: Path,
    cache_root: Path,
) -> None:
    npm = _find_npm()
    environment = dict(os.environ)
    environment.update(
        {
            "PATH": f"{npm.parent}:{environment.get('PATH', '')}",
            "ASTRO_TELEMETRY_DISABLED": "1",
            "OURNOTES_ANONTOKYO_PRIVATE_PREVIEW": "1",
            "OURNOTES_ANONTOKYO_PLAYER_GUIDE_ROOT": str(player_guide_root),
            "OURNOTES_ANONTOKYO_STAGED_MEDIA_MANIFEST": str(
                public_root / "anontokyo-media.json"
            ),
            "OURNOTES_SITE_PUBLIC_DIR": str(public_root),
            "OURNOTES_SITE_OUT_DIR": str(dist_root),
            "OURNOTES_ASTRO_CACHE_DIR": str(cache_root / "astro"),
            "OURNOTES_VITE_CACHE_DIR": str(cache_root / "vite"),
        }
    )
    try:
        subprocess.run(
            [str(npm), "run", "build:projection"],
            cwd=site_root,
            env=environment,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AnonTokyoPrivatePreviewError("private Astro build failed") from exc


def _publish_stage(stage: Path, release_root: Path) -> None:
    if not release_root.exists():
        os.replace(stage, release_root)
        return
    backup = release_root.with_name(f".{release_root.name}.previous")
    if backup.exists():
        raise AnonTokyoPrivatePreviewError("stale private preview backup exists")
    os.replace(release_root, backup)
    try:
        os.replace(stage, release_root)
    except Exception:
        os.replace(backup, release_root)
        raise
    shutil.rmtree(backup)


def build_private_preview(
    *,
    master_root: Path,
    catalog_path: Path,
    map_config_path: Path | None = None,
    audio_manifest_path: Path | None = None,
    media_root: Path | None,
    output_root: Path,
    source_release_id: str,
    site_root: Path = DEFAULT_SITE_ROOT,
    build_site: bool = True,
    generated_at: str | None = None,
    expected_counts: Mapping[str, int] | None = None,
) -> PrivatePreviewResult:
    """Build one isolated private preview release and atomically activate it."""
    master_root = master_root.resolve()
    catalog_path = catalog_path.resolve()
    map_config_path = map_config_path.resolve() if map_config_path is not None else None
    audio_manifest_path = (
        audio_manifest_path.resolve() if audio_manifest_path is not None else None
    )
    media_root = media_root.resolve() if media_root is not None else None
    output_root = output_root.resolve()
    site_root = site_root.resolve()
    if not (site_root / "package.json").is_file():
        raise AnonTokyoPrivatePreviewError("site root is invalid")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source_release_id):
        raise AnonTokyoPrivatePreviewError(
            "source_release_id must be a path-safe lowercase identifier"
        )
    if output_root == site_root or site_root in output_root.parents:
        raise AnonTokyoPrivatePreviewError(
            "private preview output must be outside the site tree"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    release_root = output_root / source_release_id
    stage = Path(
        tempfile.mkdtemp(prefix=f".{source_release_id}.partial-", dir=output_root)
    )
    try:
        projection_root = stage / "projection"
        projection = build_anontokyo_projection(
            master_root=master_root,
            catalog_path=catalog_path,
            map_config_path=map_config_path,
            output_root=projection_root,
            source_release_id=source_release_id,
            generated_at=generated_at,
        )
        counts = {
            key: int(value)
            for key, value in projection.manifest["recordCounts"].items()
        }
        if expected_counts:
            mismatches = {
                key: {"expected": expected, "actual": counts.get(key)}
                for key, expected in expected_counts.items()
                if counts.get(key) != expected
            }
            if mismatches:
                raise AnonTokyoPrivatePreviewError(
                    f"local baseline mismatch: {json.dumps(mismatches, sort_keys=True)}"
                )

        player_guide_root = stage / "player-guide"
        player_guide = build_anontokyo_player_guide(
            projection_root=projection_root,
            output_root=player_guide_root,
        )

        public_root = stage / "public"
        public_root.mkdir()
        favicon = site_root / "public/favicon.svg"
        if favicon.is_file():
            shutil.copy2(favicon, public_root / "favicon.svg")
        staged_media, staged_media_bytes = _stage_media(
            projection_root,
            player_guide_root,
            public_root,
            media_root,
        )
        staged_audio, staged_audio_bytes = _stage_audio(
            audio_manifest_path,
            public_root,
            staged_count=len(staged_media),
            staged_bytes=staged_media_bytes,
        )
        staged_media.extend(staged_audio)
        staged_media_bytes += staged_audio_bytes
        _write_json(public_root / "anontokyo-media.json", staged_media)

        dist_root = stage / "dist"
        if build_site:
            _build_astro(
                site_root=site_root,
                player_guide_root=player_guide_root,
                public_root=public_root,
                dist_root=dist_root,
                cache_root=stage / "cache",
            )

        acceptance = {
            "schemaVersion": 1,
            "sourceReleaseId": source_release_id,
            "generatedAt": projection.manifest["generatedAt"],
            "publicationState": "private_preview",
            "publicPublication": "blocked",
            "recordCounts": counts,
            "playerRecordCounts": player_guide.report["recordCounts"],
            "hiddenTasks": player_guide.report["hiddenTasks"],
            "hiddenGoods": player_guide.report["hiddenGoods"],
            "hiddenCustomers": player_guide.report["hiddenCustomers"],
            "hiddenWardrobe": player_guide.report["hiddenWardrobe"],
            "unconfirmedWardrobeAttribution": player_guide.report[
                "wardrobeUnconfirmedAttribution"
            ],
            "hiddenFurniture": player_guide.report["hiddenFurniture"],
            "unresolvedThemeFurniture": player_guide.report[
                "unresolvedThemeFurniture"
            ],
            "hiddenStages": player_guide.report["hiddenStages"],
            "hiddenMonologues": player_guide.report["hiddenMonologues"],
            "hiddenChatScenes": player_guide.report["hiddenChatScenes"],
            "reusedChatCombinations": player_guide.report[
                "reusedChatCombinations"
            ],
            "furnitureWithImages": player_guide.report["furnitureWithImages"],
            "charactersWithImages": player_guide.report["charactersWithImages"],
            "themesWithImages": player_guide.report["themesWithImages"],
            "stagesWithImages": player_guide.report["stagesWithImages"],
            "feverEffects": player_guide.report["feverEffects"],
            "wardrobeWithVerifiedAttribution": player_guide.report[
                "wardrobeWithVerifiedAttribution"
            ],
            "charactersWithUnverifiedStats": player_guide.report[
                "charactersWithUnverifiedStats"
            ],
            "bidirectionalLinks": player_guide.report["bidirectionalLinks"],
            "qualitySummary": projection.manifest["qualitySummary"],
            "formulaCapabilities": player_guide.report["formulaCapabilities"],
            "stagedMediaCount": len(staged_media),
            "stagedMediaBytes": staged_media_bytes,
            "mediaBudget": {
                "maxFiles": MAX_STAGED_MEDIA_FILES,
                "maxBytes": MAX_STAGED_MEDIA_BYTES,
            },
            "siteBuilt": build_site,
            "networkAccess": False,
        }
        _write_json(stage / "acceptance.json", acceptance)
        _publish_stage(stage, release_root)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(
            exc,
            (
                AnonTokyoPrivatePreviewError,
                AnonTokyoProjectionError,
                AnonTokyoPlayerGuideError,
            ),
        ):
            raise
        raise AnonTokyoPrivatePreviewError("private preview build failed") from exc

    return PrivatePreviewResult(
        release_root=release_root,
        projection_root=release_root / "projection",
        player_guide_root=release_root / "player-guide",
        public_root=release_root / "public",
        dist_root=release_root / "dist",
        acceptance_path=release_root / "acceptance.json",
        record_counts=counts,
        staged_media_count=len(staged_media),
        staged_media_bytes=staged_media_bytes,
    )


def serve_private_preview(*, dist_root: Path, port: int) -> None:
    if not (dist_root / "anontokyo/index.html").is_file():
        raise AnonTokyoPrivatePreviewError("private preview dist is missing")
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(dist_root), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(json.dumps({"url": f"http://127.0.0.1:{port}/anontokyo/"}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or serve the local-only AnonTokyo guide preview."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--master-root", type=Path, required=True)
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--map-config", type=Path)
    build.add_argument("--audio-manifest", type=Path)
    build.add_argument("--media-root", type=Path)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--source-release-id", required=True)
    build.add_argument("--expect-current-global-baseline", action="store_true")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--dist-root", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8766)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        serve_private_preview(dist_root=args.dist_root, port=args.port)
        return 0
    result = build_private_preview(
        master_root=args.master_root,
        catalog_path=args.catalog,
        map_config_path=args.map_config,
        audio_manifest_path=args.audio_manifest,
        media_root=args.media_root,
        output_root=args.output_root,
        source_release_id=args.source_release_id,
        expected_counts=(
            CURRENT_GLOBAL_BASELINE
            if args.expect_current_global_baseline
            else None
        ),
    )
    print(
        json.dumps(
            {
                "sourceReleaseId": args.source_release_id,
                "recordCounts": result.record_counts,
                "stagedMediaCount": result.staged_media_count,
                "url": "/anontokyo/",
                "publicationState": "private_preview",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
