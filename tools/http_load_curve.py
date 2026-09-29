#!/usr/bin/env python3
"""Run the bounded contract-defined OurNotes HTTP concurrency curve."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.http_load import run_load
from tools.performance_contract import PerformanceContract, load_performance_contract


DEFAULT_CONTRACT = REPO_ROOT / "config/performance/gates.product-v1.json"


def load_curve_contract(path: Path) -> tuple[PerformanceContract, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        load_performance_contract(path),
        f"sha256:{hashlib.sha256(canonical).hexdigest()}",
    )


def _git_head() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _default_metadata(server: str) -> dict[str, object]:
    return {
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "gitHead": _git_head(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpuCount": os.cpu_count(),
        },
        "server": server,
    }


def _ratio(value: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return round(value / baseline, 3)


def _relative_to_ten(
    summary: dict[str, Any],
    concurrency_ten: dict[str, Any],
) -> dict[str, float | None]:
    return {
        "rpsRatio": _ratio(
            float(summary["requestsPerSecond"]),
            float(concurrency_ten["requestsPerSecond"]),
        ),
        "ttfbP95Ratio": _ratio(
            float(summary["ttfbMs"]["p95"]),
            float(concurrency_ten["ttfbMs"]["p95"]),
        ),
        "totalP95Ratio": _ratio(
            float(summary["totalMs"]["p95"]),
            float(concurrency_ten["totalMs"]["p95"]),
        ),
    }


def run_curve(
    *,
    base_url: str,
    contract: PerformanceContract,
    contract_digest: str,
    timeout: float,
    stage_runner: Callable[..., dict[str, object]] = run_load,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    evidence = dict(metadata or _default_metadata("unspecified"))
    stages: list[dict[str, object]] = []
    concurrency_ten: dict[str, Any] | None = None
    hard_gate_passed = True
    for stage in contract.load_stages:
        result = stage_runner(
            base_url=base_url,
            paths=contract.load_paths,
            concurrency=stage.concurrency,
            requests=stage.requests,
            timeout=timeout,
            warmup_requests=contract.warmup_requests,
        )
        summary = dict(result["summary"])
        has_errors = int(summary["failures"]) > 0
        if stage.hard_gate:
            gate = "hard_failed" if has_errors else "hard_passed"
            hard_gate_passed = hard_gate_passed and not has_errors
        else:
            gate = "observed_with_errors" if has_errors else "observed"
        stage_report: dict[str, object] = {
            "concurrency": stage.concurrency,
            "requests": stage.requests,
            "hardGate": stage.hard_gate,
            "gate": gate,
            "summary": summary,
        }
        if stage.concurrency == 10:
            concurrency_ten = summary
        elif stage.concurrency in {20, 50} and concurrency_ten is not None:
            stage_report["relativeToConcurrency10"] = _relative_to_ten(
                summary,
                concurrency_ten,
            )
        stages.append(stage_report)

    return {
        "schemaVersion": 1,
        "startedAt": evidence["startedAt"],
        "gitHead": evidence["gitHead"],
        "environment": evidence["environment"],
        "server": evidence["server"],
        "contractDigest": contract_digest,
        "baseUrl": base_url,
        "warmupRequests": contract.warmup_requests,
        "routeSummary": {
            "method": "GET",
            "count": len(contract.load_paths),
            "paths": list(contract.load_paths),
        },
        "pass": hard_gate_passed,
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded contract-defined OurNotes HTTP load curve"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:4321")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--server", default=os.environ.get("PERF_SERVER", "unspecified"))
    parser.add_argument("--output")
    args = parser.parse_args()

    contract, contract_digest = load_curve_contract(args.contract)
    report = run_curve(
        base_url=args.base_url,
        contract=contract,
        contract_digest=contract_digest,
        timeout=args.timeout,
        metadata=_default_metadata(args.server),
    )
    print(json.dumps(report, ensure_ascii=False))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if bool(report["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
