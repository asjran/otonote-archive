"""Content-derived matching evidence for shared directories; no title/ID-only joins."""
import copy
import hashlib
import json
from pathlib import Path


def digest(value):
    def normalized(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalized(v) for v in item]
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        return item
    return hashlib.sha256(json.dumps(normalized(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def business_fields(value):
    if isinstance(value, list):
        return [business_fields(v) for v in value]
    if isinstance(value, dict):
        return {k: business_fields(v) for k, v in value.items() if k not in {
            "name", "description", "descriptionTemplate", "renderedSummary", "highestSummary", "effectName",
            "label", "sourceReleaseId", "sourceReleaseIds", "contentReleaseId", "interpretationStatus", "publicationReason", "iconEvidence",
            "relatedCardIds", "previewUrl", "containerPath", "bandName"}}
    return value


def story_identity(entry: dict, lines: list) -> str:
    # The scene, chapter, cast and episode establish the shared story identity.
    # Dialogue topology is compared separately so a revision is not exclusive.
    return digest({"scene": entry["id"], "category": entry["category"], "chapter": entry.get("chapterId"),
                   "episode": entry["episodeNumber"], "cast": entry["characterIds"], "bands": entry["bandIds"],
                   "extra": entry["isExtra"]})


def enrich_projection(name: str, value: dict, public: Path, data: Path) -> dict:
    value = copy.deepcopy(value)
    if name == "catalog.json":
        for row in value.get("musicCharts", []):
            path = data / "music-charts" / (row["id"] + ".json")
            if path.resolve().parent != (data / "music-charts").resolve():
                raise ValueError("unsafe chart record")
            if path.is_file():
                chart = json.loads(path.read_text())
                # Match source notes/timing, independently of the version of
                # the derived combo/density analysis. Scored results carry
                # their own stricter chart and calculation fingerprints.
                row["contentIdentity"] = digest({k: chart[k] for k in (
                    "difficulty", "bpmEvents", "timeSignatureEvents", "skillTimings",
                    "feverRanges", "callTimings", "notes", "paths") if k in chart})
        for row in value.get("musicTracks", []):
            charts = [chart for chart in value.get("musicCharts", []) if chart["trackId"] == row["id"]]
            score_paths = sorted(chart["scoreLogicalPath"] for chart in charts if chart.get("scoreLogicalPath"))
            if row.get("musicSoundId") and score_paths:
                # Audio binding plus original score resource paths survive
                # translations and changes to one edition's note data.
                row["contentIdentity"] = digest([row["musicSoundId"], score_paths, row.get("bandIds"), row.get("musicType")])
            row["contentComparison"] = digest([[chart.get("contentIdentity"), chart.get("level"), chart["difficulty"]]
                for chart in charts])
        for kind, folder in (("memberCards", "member-cards"), ("supportCards", "support-cards")):
            for row in value.get(kind, []):
                path = data / "database-shards" / folder / (row["id"] + ".json")
                if path.resolve().parent != (data / "database-shards" / folder).resolve():
                    raise ValueError("unsafe card record")
                if not path.is_file():
                    continue
                card = json.loads(path.read_text())["record"]
                skills = []
                for ref in card.get("skillRefs", []):
                    skill_path = data / "database-shards/skills" / (ref["skillId"] + ".json")
                    if skill_path.resolve().parent != (data / "database-shards/skills").resolve():
                        raise ValueError("unsafe skill record")
                    if skill_path.is_file():
                        skills.append(business_fields(json.loads(skill_path.read_text())["record"]))
                row["contentComparison"] = digest(skills)
    elif name == "band-items.json":
        for row in value.get("items", []):
            row["contentIdentity"] = digest(business_fields(row))
    elif name == "gallery.json":
        for kind in ("comics", "stamps", "stickers", "backgrounds"):
            for row in value.get(kind, []):
                image = row.get("image")
                if image and image.startswith("/gallery/"):
                    path = (public / image.lstrip("/")).resolve()
                    if public.resolve() not in path.parents:
                        raise ValueError("unsafe gallery image")
                    row["sourceSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif name in {"database-shards/items-index.json", "database-shards/skills-index.json"}:
        kind = "skills" if "skills-index" in name else "items"
        for row in value.get("records", []):
            path = data / "database-shards" / kind / (row["id"] + ".json")
            if path.resolve().parent != (data / "database-shards" / kind).resolve():
                raise ValueError("unsafe database record")
            if path.is_file():
                record = json.loads(path.read_text())["record"]
                if kind == "items" and record.get("imagePath"):
                    row["contentIdentity"] = digest([record["masterId"], record["typeCode"], record["imagePath"]])
                    row["contentComparison"] = digest([record.get("value"), record.get("maxOwned"), record.get("displayTargetIds")])
                else:
                    row["contentIdentity"] = digest(business_fields(record))
    elif name == "story-library.json":
        for row in value.get("entries", []):
            path = data / "story-text" / (row["id"] + ".json")
            if path.resolve().parent != (data / "story-text").resolve():
                raise ValueError("unsafe story record")
            if path.is_file():
                document = json.loads(path.read_text())
                if document.get('id') != row['id'] or document.get('sourceReleaseId') != value.get('sourceReleaseId'):
                    raise ValueError('mixed story identity')
                row['contentIdentity'] = story_identity(row, document['lines'])
                row['contentComparison'] = digest([[line['sourceIndex'],line['kind']] for line in document['lines']])
    return value


def enrich_scenes(value: dict, public: Path) -> dict:
    value = copy.deepcopy(value)
    for scene in value.get("scenes", []):
        root = scene.get("assetRoot")
        if not root or not root.startswith("/immersive/"):
            continue
        path = (public / root.lstrip("/") / "manifest.json").resolve()
        if public.resolve() not in path.parents:
            raise ValueError("unsafe scene root")
        if path.is_file():
            manifest = json.loads(path.read_text())
            files = manifest.get("files", [])
            if files:
                scene["contentIdentity"] = digest({"band": scene["bandId"], "background": scene.get("background"), "files": files})
    return value
