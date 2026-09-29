#!/usr/bin/env python3
"""Project verified game play settings and note sounds for the Auto stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MASTER_ROOT = REPO_ROOT / "input/global/decrypted/2026-09-24-v1.0.1-25/master-json"
DEFAULT_CRI_REPORT = (
    REPO_ROOT / "input/global/optional/cri-media-report.json"
)
DEFAULT_PUBLIC_ROOT = REPO_ROOT / "site/public/media/auto-se"
DEFAULT_OUTPUT = REPO_ROOT / "site/src/data/generated/auto-stage-settings.json"

SETTING_DEFINITIONS = (
    ("noteSpeed", 1, "speed", 100),
    ("noteTimingOffsetMs", 2, "ms", 1),
    ("chartPositionOffsetMs", 3, "ms", 1),
    ("judgePosition", 104, "step", 1),
    ("slideOpacity", 106, "percent", 1),
    ("guideOpacity", 107, "percent", 1),
    ("backgroundBrightness", 201, "percent", 1),
    ("laneOpacity", 300, "percent", 1),
    ("guidelineOpacity", 301, "percent", 1),
    ("noteSeVolume", 411, "percent", 1),
)

NOTE_SOUND_CUES = {
    "tap": "default_perfect",
    "flick": "default_flick",
    "flickSide": "default_flick_side",
    "long": "default_long",
    "trace": "default_trace",
}


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item for item in payload.get("_allData", [])
        if isinstance(item, Mapping)
    ]


def _number(value: Any) -> float:
    return float(str(value))


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _publish_audio(source: Path, public_root: Path, cue: str) -> str:
    digest = _sha256(source)
    target = public_root / f"{cue}-{digest[:16]}.flac"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or _sha256(target) != digest:
        target.unlink(missing_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    return f"/media/auto-se/{target.name}"


def build_auto_stage_settings(
    option_defaults: Mapping[str, Any],
    option_ranges: Mapping[str, Any],
    cri_report: Mapping[str, Any],
    *,
    public_root: Path,
) -> dict[str, Any]:
    defaults = {
        int(item.get("_optionItemType")): str(item.get("_valueString"))
        for item in _rows(option_defaults)
        if int(item.get("_presetId") or 0) == 1
    }
    ranges = {
        int(item.get("_optionItemType")): item
        for item in _rows(option_ranges)
    }
    settings = []
    for setting_id, item_type, unit, divisor in SETTING_DEFINITIONS:
        default = defaults.get(item_type)
        value_range = ranges.get(item_type)
        if default is None or value_range is None:
            continue
        settings.append({
            "id": setting_id,
            "optionItemType": item_type,
            "unit": unit,
            "default": _clean_number(_number(default)),
            "min": _clean_number(_number(value_range["_minValue"]) / divisor),
            "max": _clean_number(_number(value_range["_maxValue"]) / divisor),
            "source": "MasterOptionDefault + MasterOptionRange",
        })

    by_cue = {
        str(item.get("cue_sheet_name") or ""): item
        for item in cri_report.get("files", [])
        if isinstance(item, Mapping)
        and item.get("kind") == "audio_unity_acb"
        and item.get("ok")
    }
    note_sounds: dict[str, dict[str, Any]] = {}
    for role, cue in NOTE_SOUND_CUES.items():
        record = by_cue.get(cue)
        streams = record.get("streams", []) if record else []
        source = Path(str(streams[0].get("output"))) if streams else None
        if source is not None and not source.is_absolute():
            source = REPO_ROOT / source
        if source is not None and source.is_file():
            note_sounds[role] = {
                "state": "available",
                "cueSheet": cue,
                "url": _publish_audio(source, public_root, cue),
                "sha256": _sha256(source),
                "durationSeconds": streams[0].get("duration_seconds"),
            }
        else:
            note_sounds[role] = {
                "state": "unsupported",
                "cueSheet": cue,
                "url": None,
                "failure": {
                    "stage": "note_sound_projection",
                    "reason": "validated embedded ACB output is unavailable",
                },
            }

    return {
        "schemaVersion": 1,
        "gameSettings": settings,
        "noteSounds": note_sounds,
        "individualNoteSeDefaults": {
            "tap": 100,
            "flick": 100,
            "long": 100,
        },
        "webAnalysisSettings": [
            "playbackRate",
            "playPause",
            "seek",
            "lowPerformance",
        ],
        "excludedResourceClasses": [
            "mv",
            "vj",
            "character_voice",
            "live_voice",
            "skill_effect",
        ],
    }


def _load(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-root", type=Path, default=DEFAULT_MASTER_ROOT)
    parser.add_argument("--cri-report", type=Path, default=DEFAULT_CRI_REPORT)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_auto_stage_settings(
        _load(args.master_root / "MasterOptionDefault.json"),
        _load(args.master_root / "MasterOptionRange.json"),
        _load(args.cri_report),
        public_root=args.public_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "settings": len(result["gameSettings"]),
        "noteSounds": {
            key: value["state"] for key, value in result["noteSounds"].items()
        },
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
