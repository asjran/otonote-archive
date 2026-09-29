#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional


RESULTS = {
    "started", "success", "failed", "rollback_started",
    "rollback_succeeded", "rollback_failed",
}


def _safe(value: object, default: str = "unknown") -> str:
    text = str(value or default).replace("\r", " ").replace("\n", " ")
    return text[:256]


def build_event(
    *,
    attempt_id: str,
    command: str,
    result: str,
    release_id: str,
    git_commit: str,
    started_at: str,
    finished_at: str,
    failed_phase: Optional[str] = None,
    reason_code: Optional[str] = None,
    phases: Optional[Dict] = None,
    disk: Optional[Dict] = None,
    rsync: Optional[Dict] = None,
) -> dict:
    if result not in RESULTS:
        raise ValueError("unsupported deployment result: {}".format(result))
    if command not in {"deploy", "rollback"}:
        raise ValueError("unsupported deployment command: {}".format(command))
    return {
        "schemaVersion": 2,
        "attemptId": _safe(attempt_id),
        "command": command,
        "releaseId": _safe(release_id),
        "gitCommit": _safe(git_commit),
        "startedAt": _safe(started_at),
        "finishedAt": _safe(finished_at),
        "result": result,
        "failedPhase": _safe(failed_phase, "") or None,
        "reasonCode": _safe(reason_code, "") or None,
        "phases": dict(phases or {}),
        "disk": dict(disk or {}),
        "rsync": dict(rsync or {}),
    }


def append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and append a deployment lifecycle event")
    parser.add_argument("--output", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--command", choices=("deploy", "rollback"), required=True)
    parser.add_argument("--result", choices=sorted(RESULTS), required=True)
    parser.add_argument("--release-id", default="unknown")
    parser.add_argument("--git-commit", default="unknown")
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", required=True)
    parser.add_argument("--failed-phase")
    parser.add_argument("--reason-code")
    parser.add_argument("--phases-json", default="{}")
    parser.add_argument("--disk-json", default="{}")
    parser.add_argument("--rsync-json", default="{}")
    args = parser.parse_args()
    event = build_event(
        attempt_id=args.attempt_id,
        command=args.command,
        result=args.result,
        release_id=args.release_id,
        git_commit=args.git_commit,
        started_at=args.started_at,
        finished_at=args.finished_at,
        failed_phase=args.failed_phase,
        reason_code=args.reason_code,
        phases=json.loads(args.phases_json),
        disk=json.loads(args.disk_json),
        rsync=json.loads(args.rsync_json),
    )
    append_event(Path(args.output), event)
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
