"""Build an auditable Live2D conversion, browser, and fallback capability report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = REPO_ROOT / "site/src/data/generated/live2d-models.json"
DEFAULT_CHARACTER_MEDIA = REPO_ROOT / "site/src/data/generated/character-media.json"
DEFAULT_BROWSER = REPO_ROOT / "analysis/live2d-browser-validation.json"
DEFAULT_OUTPUT = REPO_ROOT / "analysis/live2d-capability-report.json"


def build_capability_report(
    models_payload: Mapping[str, Any],
    character_media: Mapping[str, Any],
    browser_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    costumes = [
        item for item in character_media.get("costumes", [])
        if isinstance(item, Mapping)
    ]
    costume_counts = Counter(str(item.get("live2dPath") or "") for item in costumes)
    fallback_by_model = {
        model_id: any(
            str(item.get("previewState") or "") not in {"", "missing"}
            for item in costumes
            if str(item.get("live2dPath") or "") == model_id
        )
        for model_id in costume_counts
    }
    browser_by_model = {
        str(item.get("modelId") or ""): item
        for item in (browser_payload or {}).get("results", [])
        if isinstance(item, Mapping)
    }
    entries: list[dict[str, Any]] = []
    for model in models_payload.get("models", []):
        if not isinstance(model, Mapping):
            continue
        model_id = str(model.get("modelId") or "")
        conversion_available = model.get("state") == "available"
        browser = browser_by_model.get(model_id)
        browser_state = str((browser or {}).get("state") or "pending")
        converted_motion_state = str(
            model.get("motionState") or "not_selected"
        )
        motion_state = (
            "supported_motion"
            if (
                converted_motion_state == "converted_motion"
                and str((browser or {}).get("motionState") or "") == "passed"
            )
            else converted_motion_state
        )
        fallback_available = bool(fallback_by_model.get(model_id))
        if conversion_available and browser_state == "passed":
            portrait_state = "supported_portrait"
        elif not conversion_available and fallback_available:
            portrait_state = "degraded"
        else:
            portrait_state = str(model.get("portraitState") or "experimental")
        entries.append({
            "modelId": model_id,
            "conversionState": str(model.get("state") or "unsupported"),
            "portraitState": portrait_state,
            "expressionState": str(model.get("expressionState") or "absent"),
            "motionState": motion_state,
            "motionPublicationState": str(
                model.get("motionPublicationState") or "blocked"
            ),
            "physicsState": str(model.get("physicsState") or "absent"),
            "browserState": browser_state,
            "fallbackState": "available" if fallback_available else "missing",
            "coreBytes": int(model.get("coreBytes") or 0),
            "optionalBytes": int(model.get("optionalBytes") or 0),
            "sourceMotionCount": int(model.get("sourceMotionCount") or 0),
            "supportedMotionCount": int(model.get("supportedMotionCount") or 0),
            "publishedMotionCount": int(model.get("motionCount") or 0),
            "blockedMotionCount": int(model.get("blockedMotionCount") or 0),
            "linkedCostumeCount": int(costume_counts.get(model_id, 0)),
            "failure": model.get("failure"),
        })
    known_ids = {entry["modelId"] for entry in entries}
    linked_closure_count = sum(
        count
        for model_id, count in costume_counts.items()
        if (
            next(
                (
                    entry["conversionState"] == "available"
                    or entry["fallbackState"] == "available"
                    for entry in entries
                    if entry["modelId"] == model_id
                ),
                False,
            )
        )
    )
    by_conversion = Counter(entry["conversionState"] for entry in entries)
    return {
        "schemaVersion": 1,
        "summary": {
            "candidateCount": len(entries),
            "conversionByState": dict(sorted(by_conversion.items())),
            "linkedCostumeCount": len(costumes),
            "linkedUniqueModelCount": len(costume_counts),
            "linkedUnknownModelCount": sum(
                count for model_id, count in costume_counts.items()
                if model_id not in known_ids
            ),
            "linkedCostumeClosureCount": linked_closure_count,
            "supportedPortraitModelCount": sum(
                entry["portraitState"] == "supported_portrait"
                for entry in entries
            ),
            "supportedMotionModelCount": sum(
                entry["motionState"] == "supported_motion"
                for entry in entries
            ),
            "plannedMotionModelCount": sum(
                entry["motionPublicationState"] == "planned"
                for entry in entries
            ),
            "sourceMotionCount": sum(
                entry["sourceMotionCount"] for entry in entries
            ),
            "convertibleMotionCount": sum(
                entry["supportedMotionCount"] for entry in entries
            ),
            "publishedMotionCount": sum(
                entry["publishedMotionCount"] for entry in entries
            ),
            "blockedMotionCount": sum(
                entry["blockedMotionCount"] for entry in entries
            ),
            "linkedSourceMotionCount": sum(
                entry["sourceMotionCount"]
                for entry in entries
                if entry["linkedCostumeCount"] > 0
            ),
            "linkedConvertibleMotionCount": sum(
                entry["supportedMotionCount"]
                for entry in entries
                if entry["linkedCostumeCount"] > 0
            ),
            "linkedPublishedMotionCount": sum(
                entry["publishedMotionCount"]
                for entry in entries
                if entry["linkedCostumeCount"] > 0
            ),
            "linkedBlockedMotionCount": sum(
                entry["blockedMotionCount"]
                for entry in entries
                if entry["linkedCostumeCount"] > 0
            ),
            "coreBytes": sum(entry["coreBytes"] for entry in entries),
            "optionalBytes": sum(entry["optionalBytes"] for entry in entries),
        },
        "models": entries,
    }


def _load_optional(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--character-media", type=Path, default=DEFAULT_CHARACTER_MEDIA)
    parser.add_argument("--browser", type=Path, default=DEFAULT_BROWSER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = build_capability_report(
        json.loads(args.models.read_text(encoding="utf-8")),
        json.loads(args.character_media.read_text(encoding="utf-8")),
        _load_optional(args.browser),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
