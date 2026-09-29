#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


MEDIA_SUFFIXES = {".moc3", ".flac", ".wav", ".mp4", ".webm", ".m4a", ".mp3", ".aac"}


def is_large_media_url(value: str) -> bool:
    clean = value.lower().split("?", 1)[0].split("#", 1)[0]
    return any(clean.endswith(suffix) for suffix in MEDIA_SUFFIXES)


class MediaPreloadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.media_stack: list[bool] = []
        self.unsafe: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"audio", "video"}:
            allowed = values.get("preload", "").lower() == "none"
            self.media_stack.append(allowed)
            source = values.get("src") or ""
            if is_large_media_url(source) and not allowed:
                self.unsafe.append(source)
        elif tag == "source":
            source = values.get("src") or ""
            if is_large_media_url(source) and not (self.media_stack and self.media_stack[-1]):
                self.unsafe.append(source)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag in {"audio", "video"} and self.media_stack:
            self.media_stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"audio", "video"} and self.media_stack:
            self.media_stack.pop()


def analyze_artifact(root: Path) -> dict[str, Any]:
    """Summarize a built artifact by file type and rendered HTML route."""
    groups: dict[str, list[int]] = {}
    largest: list[dict[str, object]] = []
    routes: dict[str, dict[str, int]] = {}
    forbidden_html: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        suffix = path.suffix.lower() or "[none]"
        size = path.stat().st_size
        groups.setdefault(suffix, []).append(size)
        largest.append({"path": relative.as_posix(), "bytes": size})
        if suffix == ".html":
            route = (
                f"{relative.parent.as_posix()}/"
                if relative.parent.as_posix() != "."
                else "/"
            )
            payload = path.read_bytes()
            routes[route] = {
                "bytes": size,
                "gzipBytes": len(gzip.compress(payload, mtime=0)),
            }
            media_parser = MediaPreloadParser()
            media_parser.feed(payload.decode("utf-8", errors="replace"))
            if media_parser.unsafe:
                forbidden_html.append(
                    {
                        "path": relative.as_posix(),
                        "sources": media_parser.unsafe[:10],
                    }
                )
    summary = {
        suffix: {
            "count": len(sizes),
            "bytes": sum(sizes),
            "maxBytes": max(sizes),
            "medianBytes": sorted(sizes)[len(sizes) // 2],
        }
        for suffix, sizes in sorted(groups.items())
    }
    return {
        "root": str(root),
        "files": sum(len(sizes) for sizes in groups.values()),
        "bytes": sum(sum(sizes) for sizes in groups.values()),
        "types": summary,
        "routes": dict(sorted(routes.items())),
        "largest": sorted(
            largest,
            key=lambda item: int(item["bytes"]),
            reverse=True,
        )[:100],
        "unsafeHtml": forbidden_html,
    }


def compare_reports(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Return release-to-release growth without hiding removed routes."""
    baseline_bytes = int(baseline.get("bytes", 0))
    current_routes = current.get("routes", {})
    baseline_routes = baseline.get("routes", {})
    route_delta: dict[str, dict[str, int]] = {}
    for route in sorted(set(current_routes) | set(baseline_routes)):
        current_route = current_routes.get(route, {})
        baseline_route = baseline_routes.get(route, {})
        route_delta[route] = {
            "bytes": int(current_route.get("bytes", 0))
            - int(baseline_route.get("bytes", 0)),
            "gzipBytes": int(current_route.get("gzipBytes", 0))
            - int(baseline_route.get("gzipBytes", 0)),
        }
    byte_delta = int(current.get("bytes", 0)) - baseline_bytes
    return {
        "files": int(current.get("files", 0))
        - int(baseline.get("files", 0)),
        "bytes": byte_delta,
        "percentBytes": (
            round(byte_delta / baseline_bytes * 100, 2)
            if baseline_bytes
            else None
        ),
        "routes": route_delta,
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser(
        description="Report public resource sizes and reject unsafe artifacts"
    )
    argument_parser.add_argument(
        "root",
        nargs="?",
        default="site/dist-matrix",
    )
    argument_parser.add_argument(
        "--output",
        default="site/output/performance/build-budget.json",
    )
    argument_parser.add_argument("--baseline")
    argument_parser.add_argument("--max-growth-percent", type=float)
    args = argument_parser.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        argument_parser.error(f"build root does not exist: {root}")
    report = analyze_artifact(root)
    if args.baseline:
        baseline_path = Path(args.baseline)
        try:
            baseline = json.loads(
                baseline_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            argument_parser.error(f"cannot read baseline: {exc}")
        report["delta"] = compare_reports(report, baseline)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: report[key] for key in ("files", "bytes")},
            ensure_ascii=False,
        )
    )
    if report["unsafeHtml"]:
        print(
            json.dumps(
                {"unsafeHtml": report["unsafeHtml"]},
                ensure_ascii=False,
            )
        )
        return 1
    if (
        args.max_growth_percent is not None
        and isinstance(report.get("delta"), dict)
        and report["delta"].get("percentBytes") is not None
        and report["delta"]["percentBytes"] > args.max_growth_percent
    ):
        print(
            json.dumps(
                {
                    "growthPercent": report["delta"]["percentBytes"],
                    "maxGrowthPercent": args.max_growth_percent,
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
