#!/usr/bin/env python3

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def fetch(url: str, timeout: float) -> dict[str, object]:
    started = time.perf_counter()
    ttfb_ms = 0.0
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "OurNotesSyntheticLoad/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            ttfb_ms = (time.perf_counter() - started) * 1000
            body = response.read()
            status = response.status
        error = None
    except urllib.error.HTTPError as exc:
        ttfb_ms = (time.perf_counter() - started) * 1000
        body = exc.read()
        status = exc.code
        error = str(exc)
    except (urllib.error.URLError, TimeoutError) as exc:
        body = b""
        status = 0
        error = str(exc)
    total_ms = (time.perf_counter() - started) * 1000
    return {
        "url": url,
        "status": status,
        "bytes": len(body),
        "ttfbMs": round(ttfb_ms, 2),
        "totalMs": round(total_ms, 2),
        "elapsedMs": round(total_ms, 2),
        "error": error,
    }


def _timing_summary(values: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def _request_urls(
    base_url: str,
    paths: Sequence[str],
    requests: int,
) -> list[str]:
    return [
        base_url.rstrip("/") + paths[index % len(paths)]
        for index in range(requests)
    ]


def _execute_requests(
    urls: list[str],
    concurrency: int,
    timeout: float,
    fetcher: Callable[[str, float], dict[str, object]],
) -> list[dict[str, object]]:
    if not urls:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(lambda url: fetcher(url, timeout), urls))


def run_load(
    *,
    base_url: str,
    paths: Sequence[str],
    concurrency: int,
    requests: int,
    timeout: float,
    warmup_requests: int = 0,
    fetcher: Callable[[str, float], dict[str, object]] = fetch,
) -> dict[str, object]:
    if not 1 <= concurrency <= 50 or not 1 <= requests <= 1000:
        raise ValueError("concurrency must be 1..50 and requests must be 1..1000")
    if not 0 <= warmup_requests <= 1000:
        raise ValueError("warmup requests must be 0..1000")
    if not paths:
        raise ValueError("at least one GET path is required")

    _execute_requests(
        _request_urls(base_url, paths, warmup_requests),
        concurrency,
        timeout,
        fetcher,
    )
    urls = _request_urls(base_url, paths, requests)
    started = time.perf_counter()
    results = _execute_requests(urls, concurrency, timeout, fetcher)
    duration = time.perf_counter() - started
    ttfb_timings = [float(result["ttfbMs"]) for result in results]
    total_timings = [float(result["totalMs"]) for result in results]
    failures = [
        result
        for result in results
        if int(result["status"]) < 200 or int(result["status"]) >= 400
    ]
    ttfb_summary = _timing_summary(ttfb_timings)
    total_summary = _timing_summary(total_timings)
    summary = {
        "baseUrl": base_url,
        "concurrency": concurrency,
        "requests": len(results),
        "warmupRequests": warmup_requests,
        "durationSeconds": round(duration, 3),
        "requestsPerSecond": round(len(results) / duration, 3),
        "bytes": sum(int(result["bytes"]) for result in results),
        "failures": len(failures),
        "errorRate": round(len(failures) / len(results), 6),
        "ttfbMs": ttfb_summary,
        "totalMs": total_summary,
        "p50Ms": total_summary["p50"],
        "p95Ms": total_summary["p95"],
        "p99Ms": total_summary["p99"],
        "maxMs": total_summary["max"],
    }
    return {"summary": summary, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded read-only OurNotes HTTP load test")
    parser.add_argument("--base-url", default="http://127.0.0.1:4321")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output")
    parser.add_argument("--path", action="append", dest="paths")
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 50 or not 1 <= args.requests <= 1000:
        parser.error("concurrency must be 1..50 and requests must be 1..1000")
    paths = args.paths or ["/global/zh-CN/", "/global/zh-CN/tools/", "/global/zh-CN/characters/", "/global/zh-CN/music/"]
    payload = run_load(
        base_url=args.base_url,
        paths=paths,
        concurrency=args.concurrency,
        requests=args.requests,
        timeout=args.timeout,
    )
    summary = payload["summary"]
    print(json.dumps(summary, ensure_ascii=False))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 1 if int(summary["failures"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
