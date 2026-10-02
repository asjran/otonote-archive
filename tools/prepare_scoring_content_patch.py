"""Extract an audited scoring patch without publishing or rewriting a snapshot.

The production manifests must be downloaded separately and match the captured
deployment baseline. Original chart bytes must match those manifests, and the
audited charts may differ only in derived projection fields. The output carries
per-file preconditions; activation and new snapshot identities are deliberately
left to the publication workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile


MODEL = "ournotes-native-score-v5"
CHART_MODEL = "formal-chart-v2"
STATS = ("judgementCount", "judgementCountSource", "sourceJudgementCount",
         "explicitJudgementCount", "slideComboCandidateCount", "skippedSlideComboCount",
         "mergedEndpointReduction", "averageDensity", "peakDensity")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def bound_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("unsafe artifact path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe artifact path")
    target = Path(root).joinpath(*parts)
    if target.is_symlink() or not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("unsafe artifact target")
    return target


def checked_bytes(root, record):
    raw = bound_path(root, record["path"]).read_bytes()
    if digest(raw) != record["sha256"] or len(raw) != record["bytes"]:
        raise ValueError("artifact differs from bound manifest: " + record["path"])
    return raw


def authored_chart(chart):
    value = {key: item for key, item in chart.items()
             if key not in ("comboEvents", "density", "statistics", "duration", "meta")}
    value["meta"] = {key: item for key, item in chart.get("meta", {}).items()
                     if key != "runtimeAlgorithmVersion"}
    return value


def chart_updates(chart, summary):
    stats = chart["statistics"]
    events = chart["comboEvents"]
    ids = [event.get("nativeNoteId") for event in events]
    if chart.get("meta", {}).get("runtimeAlgorithmVersion") != CHART_MODEL:
        raise ValueError("audited chart model mismatch: " + chart["id"])
    if (any(type(value) is not int or value < 0 for value in ids)
            or len(set(ids)) != len(ids)
            or stats["runtimeFullCombo"] != len(events)
            or stats["judgementCount"] != len(events)):
        raise ValueError("invalid native chart IDs or counts: " + chart["id"])
    delta = len(events) - summary["masterFullComboCount"]
    return {**{key: stats[key] for key in STATS},
            "fullComboCount": len(events), "fullComboDelta": delta,
            "fullComboClassification": "MATCH" if delta == 0 else "RUNTIME_HIGHER" if delta > 0 else "RUNTIME_LOWER",
            "fullComboStatus": "match" if delta == 0 else "conflict",
            "duration": chart["duration"], "runtimeAlgorithmVersion": CHART_MODEL}


def extract_patch(baseline_path, manifests, source, original_source, output):
    baseline_path, manifests = Path(baseline_path), Path(manifests)
    source, original_source, output = Path(source), Path(original_source), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("patch output already exists")
    for protected in (source.resolve(), original_source.resolve(), manifests.resolve()):
        if output.resolve() == protected or output.resolve() in protected.parents or protected in output.resolve().parents:
            raise ValueError("patch output overlaps a content source")
    baseline = read_json(baseline_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".scoring-patch-", dir=output.parent))
    patch = {"schemaVersion": 1, "modelVersion": MODEL, "chartModelVersion": CHART_MODEL,
             "baselineSha256": digest(baseline_path.read_bytes()), "regions": {}}
    try:
        for region in ("global", "jp"):
            before = baseline["contents"][region]
            pointer = before["pointer"]
            match = re.fullmatch(r"/content/releases/([a-f0-9]{24})/manifest.json", pointer["manifest"])
            if not match:
                raise ValueError("invalid production snapshot pointer")
            snapshot = match[1]
            manifest_raw = (manifests / snapshot / "manifest.json").read_bytes()
            if digest(manifest_raw) != pointer["sha256"] or pointer["sha256"] != before["manifestSha256"]:
                raise ValueError("production manifest differs from captured baseline")
            manifest = json.loads(manifest_raw)
            root = source / "releases" / snapshot
            original_root = original_source / "releases" / snapshot
            verified = read_json(root / "manifest.json")
            if (manifest["region"] != region or verified["region"] != region
                    or manifest["contentReleaseId"] != pointer["contentReleaseId"]
                    or verified["contentReleaseId"] != pointer["contentReleaseId"]
                    or manifest["root"] != f"/content/releases/{snapshot}/"
                    or verified["root"] != manifest["root"]
                    or set(manifest["locales"]) != {"zh-CN", "en"}
                    or set(verified["locales"]) != {"zh-CN", "en"}):
                raise ValueError("content source identity mismatch")
            item = {"expectedPointer": pointer, "expectedManifestSha256": pointer["sha256"],
                    "expectedCandidateSha256": before["candidateSha256"],
                    "auditedManifestSha256": digest((root / "manifest.json").read_bytes()),
                    "preconditions": [], "replacements": [], "catalogUpdates": [], "locales": {}}
            patch["regions"][region] = item
            for locale in ("zh-CN", "en"):
                records = manifest["locales"][locale]["files"]
                audited = verified["locales"][locale]["files"]
                catalog_record = records["projection/catalog.json"]
                # The verification rebuild intentionally preserved each locale's
                # catalog, so this also binds chart membership and Master counts.
                catalog = json.loads(checked_bytes(root, catalog_record))
                rule_key = "supplemental/formal-scoring-rules.json"
                rules = json.loads(checked_bytes(root, records[rule_key]))
                if catalog["release"]["id"] != pointer["contentReleaseId"] or rules["sourceReleaseId"] != pointer["contentReleaseId"]:
                    raise ValueError("catalog or rules release mismatch")
                item["preconditions"].append({"key": rule_key, "locale": locale, **records[rule_key]})
                chart_changes, track_changes, chart_ids = {}, {}, set()
                total_events = 0

                def replacement(key, raw):
                    record = records[key]
                    name = "payloads/" + digest(raw) + ".json"
                    payload = stage / name
                    if not payload.exists():
                        payload.parent.mkdir(exist_ok=True)
                        payload.write_bytes(raw)
                    item["replacements"].append({"key": key, "locale": locale, "path": record["path"],
                        "expectedSha256": record["sha256"], "expectedBytes": record["bytes"],
                        "sha256": digest(raw), "bytes": len(raw), "payloadPath": name})

                for summary in catalog["musicCharts"]:
                    chart_id = summary["id"]
                    if chart_id in chart_ids:
                        raise ValueError("duplicate catalog chart")
                    chart_ids.add(chart_id)
                    key = f"projection/music-charts/{chart_id}.json"
                    original = json.loads(checked_bytes(original_root, records[key]))
                    raw = checked_bytes(root, audited[key])
                    chart = json.loads(raw)
                    if (chart["id"] != chart_id or chart["trackId"] != summary["trackId"]
                            or chart["difficulty"] != summary["difficulty"]
                            or authored_chart(chart) != authored_chart(original)
                            or len(chart["comboEvents"]) != len(original["comboEvents"])):
                        raise ValueError("authored chart or event count changed: " + chart_id)
                    chart_changes[chart_id] = chart_updates(chart, summary)
                    if chart["difficulty"] == "expert":
                        track_changes[chart["trackId"]] = {"expertNoteCount": len(chart["comboEvents"])}
                    total_events += len(chart["comboEvents"])
                    replacement(key, raw)
                rank_key = "supplemental/song-rankings.json"
                rank_raw = checked_bytes(root, audited[rank_key])
                rankings = json.loads(rank_raw)
                if (rankings["sourceReleaseId"] != pointer["contentReleaseId"]
                        or rankings.get("benchmark", {}).get("modelVersion") != MODEL
                        or not rankings.get("fingerprint") or not rankings.get("rulesFingerprint")):
                    raise ValueError("audited ranking model or release mismatch")
                for mode in ("ordinary", "gekisou"):
                    rows = rankings[mode]
                    if len(rows) != len(chart_ids) or {row["id"] for row in rows} != chart_ids:
                        raise ValueError("audited ranking coverage mismatch")
                    for row in rows:
                        if (row["eventCount"] != chart_changes[row["id"]]["fullComboCount"]
                                or not row.get("chartFingerprint") or not row.get("meta")):
                            raise ValueError("audited ranking event or metadata mismatch")
                replacement(rank_key, rank_raw)
                item["catalogUpdates"].append({"key": "projection/catalog.json", "locale": locale,
                    "path": catalog_record["path"], "expectedSha256": catalog_record["sha256"],
                    "expectedBytes": catalog_record["bytes"], "musicCharts": chart_changes, "musicTracks": track_changes})
                item["locales"][locale] = {"charts": len(chart_ids), "events": total_events,
                                           "replacements": len(chart_ids) + 1}
        (stage / "patch.json").write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n")
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    patch = extract_patch(args.baseline, args.manifests, args.source, args.original_source, args.output)
    print(json.dumps({"modelVersion": MODEL, "regions": {region: item["locales"]
        for region, item in patch["regions"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
