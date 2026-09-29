#!/usr/bin/env python3
"""Load the versioned performance-gate contract used by browser and load tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Union


EXPECTED_LOCALES = ("zh-CN", "en")
EXPECTED_VIEWPORTS = (
    ("desktop", 1440, 900),
    ("mobile", 390, 844),
)
PRODUCT_V1_ROUTES = {"home", "tools", "music", "characters", "character-detail", "member-detail", "support-detail", "music-detail", "events"}
EXPECTED_BROWSER_ROUTE_COUNT = 9
EXPECTED_BROWSER_CASE_COUNT = 36
EXPECTED_LOAD_PATHS = (
    "/global/zh-CN/",
    "/global/zh-CN/tools/",
    "/global/zh-CN/cards/",
    "/global/zh-CN/characters/",
    "/global/zh-CN/music/",
    "/global/zh-CN/events/",
)
EXPECTED_WARMUP_REQUESTS = 6


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int


@dataclass(frozen=True)
class BrowserCase:
    id: str
    route_id: str
    locale: str
    path: str
    viewport: Viewport
    max_bytes: int
    max_requests: int


@dataclass(frozen=True)
class LoadStage:
    concurrency: int
    requests: int
    hard_gate: bool


@dataclass(frozen=True)
class PerformanceContract:
    schema_version: int
    browser_cases: tuple[BrowserCase, ...]
    load_paths: tuple[str, ...]
    load_stages: tuple[LoadStage, ...]
    warmup_requests: int
    max_byte_growth_ratio: float
    max_request_growth: int


def _validate_browser_route_template(value: object) -> str:
    path = str(value)
    if (
        not path.startswith("/global/{locale}/")
        or path.count("{locale}") != 1
        or any(token in path for token in ("?", "#", "\\", "%", "://"))
        or "//" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise ValueError(f"unsafe browser route template: {path}")
    return path


def _validate_load_path(value: object, locales: tuple[str, ...]) -> str:
    path = str(value)
    if (
        not any(path.startswith(f"/global/{locale}/") for locale in locales)
        or "{" in path
        or "}" in path
        or any(token in path for token in ("?", "#", "\\", "%", "://"))
        or "//" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise ValueError(f"unsafe load path: {path}")
    return path


def load_performance_contract(path: Union[str, Path]) -> PerformanceContract:
    """Parse one performance contract and expand its browser case matrix."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    schema_version = int(payload["schemaVersion"])
    if schema_version != 1:
        raise ValueError(
            f"unsupported performance contract schemaVersion: {schema_version}"
        )
    profile = payload.get("productProfile", "v1")
    if profile != "v1":
        raise ValueError(f"unsupported product profile: {profile}")
    route_count = EXPECTED_BROWSER_ROUTE_COUNT
    case_count = EXPECTED_BROWSER_CASE_COUNT
    load_path_contract = EXPECTED_LOAD_PATHS
    locales = tuple(str(value) for value in payload["locales"])
    if locales != EXPECTED_LOCALES:
        raise ValueError(f"noncanonical v1 browser matrix locales: {locales!r}")
    viewports = tuple(
        Viewport(
            name=str(value["name"]),
            width=int(value["width"]),
            height=int(value["height"]),
        )
        for value in payload["viewports"]
    )
    actual_viewports = tuple(
        (value.name, value.width, value.height) for value in viewports
    )
    if actual_viewports != EXPECTED_VIEWPORTS:
        raise ValueError(
            f"noncanonical v1 browser matrix viewports: {actual_viewports!r}"
        )
    browser = payload["browser"]
    if len(browser["routes"]) != route_count:
        raise ValueError(
            "noncanonical v1 browser matrix route count: "
            f"{len(browser['routes'])}"
        )
    max_byte_growth_ratio = float(browser["maxByteGrowthRatio"])
    max_request_growth = int(browser["maxRequestGrowth"])
    if max_byte_growth_ratio <= 0 or max_request_growth <= 0:
        raise ValueError(
            "browser budget growth limits must be positive"
        )
    cases = []
    route_ids: set[str] = set()
    for route in browser["routes"]:
        route_id = str(route["id"])
        if not route_id or route_id in route_ids:
            raise ValueError(f"duplicate or empty browser route id: {route_id}")
        route_ids.add(route_id)
        route_template = _validate_browser_route_template(route["path"])
        max_bytes = int(route["maxBytes"])
        max_requests = int(route["maxRequests"])
        if max_bytes <= 0 or max_requests <= 0:
            raise ValueError(
                f"browser budget must be positive for route: {route_id}"
            )
        for locale in locales:
            expanded_path = route_template.replace("{locale}", locale)
            for viewport in viewports:
                cases.append(
                    BrowserCase(
                        id=f"{route_id}.{locale}.{viewport.name}",
                        route_id=route_id,
                        locale=locale,
                        path=expanded_path,
                        viewport=viewport,
                        max_bytes=max_bytes,
                        max_requests=max_requests,
                    )
                )
    if profile == "v1" and route_ids != PRODUCT_V1_ROUTES:
        raise ValueError("noncanonical product v1 browser routes")
    if len(cases) != case_count:
        raise ValueError(
            f"noncanonical v1 browser matrix case count: {len(cases)}"
        )
    load = payload["load"]
    stages = tuple(
        LoadStage(
            concurrency=int(value["concurrency"]),
            requests=int(value["requests"]),
            hard_gate=bool(value["hardGate"]),
        )
        for value in load["stages"]
    )
    actual_curve = tuple(
        (stage.concurrency, stage.requests, stage.hard_gate) for stage in stages
    )
    expected_curve = (
        (5, 100, True),
        (10, 200, True),
        (20, 200, False),
        (50, 100, False),
    )
    if actual_curve != expected_curve:
        raise ValueError(
            f"noncanonical v1 load curve: {actual_curve!r}"
        )
    load_paths = tuple(
        _validate_load_path(value, locales) for value in load["paths"]
    )
    warmup_requests = int(load["warmupRequests"])
    if load_paths != load_path_contract:
        raise ValueError(
            f"noncanonical v1 load contract paths: {load_paths!r}"
        )
    if warmup_requests != EXPECTED_WARMUP_REQUESTS:
        raise ValueError(
            "noncanonical v1 load contract warmupRequests: "
            f"{warmup_requests}"
        )
    return PerformanceContract(
        schema_version=schema_version,
        browser_cases=tuple(cases),
        load_paths=load_paths,
        load_stages=stages,
        warmup_requests=warmup_requests,
        max_byte_growth_ratio=max_byte_growth_ratio,
        max_request_growth=max_request_growth,
    )
