"""Exercise every entity in a real bundle and retain representative image evidence."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from backend.qqbot.content import Content
from backend.qqbot.query import COMMANDS, Queries, clean
from backend.qqbot.render import Renderer


SAMPLES = [("card", "查角色卡 51"), ("snap", "查留影 51"), ("song", "查歌曲 100001"),
           ("gacha", "查卡池 1"), ("character", "查角色 1"), ("help", "帮助"),
           ("list", "查角色卡"), ("empty", "查歌曲 不存在的曲目"),
           ("future", "查活动档线"), ("studio", "查录音室进度")]


def run(bundle: Path, output: Path, font: str | None = None, *, content=None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    content = content or Content(bundle)
    queries, renderer = Queries(content), Renderer(content.snapshot, font)
    report = {"executedAt": datetime.now(timezone.utc).isoformat(), "releaseId": content.release_id,
              "scope": "local_real_snapshot_not_qq_sandbox", "bundleManifestSha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest(),
              "features": {}, "samples": [], "failures": []}
    started = time.monotonic()
    for command, dataset in COMMANDS.items():
        items = content.systems[dataset] if dataset == "gachaPools" else content.catalog[dataset]
        stats = {"entities": len(items), "queryPassed": 0, "renderPassed": 0, "images": 0, "maxImageBytes": 0, "missingArtwork": 0}
        for item in items:
            try:
                reply = queries.query(f"{command} {item['id']}")
                expected = clean(item.get("displayName") or item.get("title") or item.get("name"))
                if reply.title != expected:
                    raise AssertionError("stable ID did not resolve to the expected entity")
                stats["queryPassed"] += 1
                if reply.image is None:
                    stats["missingArtwork"] += 1
                images = renderer.render(reply)
                if not 1 <= len(images) <= 4:
                    raise AssertionError("reply image count outside QQ limit")
                for image in images:
                    with Image.open(io.BytesIO(image)) as png:
                        png.load()
                        if png.format != "PNG" or png.width != 900 or png.height > 2500:
                            raise AssertionError("invalid image dimensions")
                    if len(image) > 5 * 1024 * 1024:
                        raise AssertionError("image exceeds local 5MB budget")
                    stats["maxImageBytes"] = max(stats["maxImageBytes"], len(image))
                stats["images"] += len(images)
                stats["renderPassed"] += 1
            except Exception as exc:
                report["failures"].append({"command": command, "id": item["id"], "error": type(exc).__name__ + ": " + str(exc)})
        report["features"][command] = stats
        print(command, stats, flush=True)
    for name, command in SAMPLES:
        for index, image in enumerate(renderer.render(queries.query(command)), 1):
            filename = f"{name}-{index}.png"
            (output / filename).write_bytes(image)
            report["samples"].append({"command": command, "file": filename, "sha256": hashlib.sha256(image).hexdigest()})
    thumbnails = []
    for index, (name, command) in enumerate(SAMPLES[:5]):
        with Image.open(output / f"{name}-1.png") as source:
            source.thumbnail((350, 1530))
            thumbnails.append(source.copy())
    sheet = Image.new("RGB", (1800, max(x.height for x in thumbnails) + 70), "#DEE3EF")
    for index, source in enumerate(thumbnails):
        sheet.paste(source, (index * 360 + (350 - source.width) // 2, 50))
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 12), "OUR NOTES / QQ BOT / FIVE IMAGE TEMPLATES", fill="#202744")
    sheet.save(output / "contact-sheet.png")
    report["elapsedSeconds"] = round(time.monotonic() - started, 3)
    report["passed"] = not report["failures"]
    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--font")
    args = parser.parse_args()
    report = run(args.bundle, args.output, args.font)
    print(json.dumps({"passed": report["passed"], "elapsedSeconds": report["elapsedSeconds"]}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
