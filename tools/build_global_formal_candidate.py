"""Build one pinned Global production core candidate without activating it."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_candidates import compile_core
from tools.release_preflight import PreflightError, check_environment, load_plan
from tools.score_inputs import read_score_inputs


def build(output: Path, *, root: Path = ROOT, plan: Path | None = None) -> dict:
    plan = plan or root / "config/release-inputs.json"
    source = next((entry for entry in load_plan(plan) if entry["id"] == "global-production"), None)
    if source is None or check_environment(source, root)["status"] != "passed":
        raise PreflightError("Global production input has not passed preflight")
    if not source.get("extractedRoot") or not (root / source["extractedRoot"]).is_dir():
        raise PreflightError("Global production extractedRoot is missing")
    if read_score_inputs(source, root) is None:
        raise PreflightError("Global production score inputs are not bound")
    output = output.resolve()
    protected = [root / name for name in ("site", "catalog", "input", "data", "config", "phone_dump")]
    protected += [(root / source[field]).resolve() for field in
                  ("manifest", "masterRoot", "assetManifest", "extractedRoot")]
    protected.append((root / source["scoreInputs"]["index"]).resolve().parent)
    if output.exists() or output.is_symlink() or any(
        output == path or output in path.parents or path in output.parents for path in protected
    ):
        raise PreflightError("candidate output exists or overlaps protected input")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        result = compile_core(source, temporary, ("zh-CN", "zh-TW", "ja", "en"), root)
        report = {"environment": "global-production", "contentReleaseId": source["contentReleaseId"],
                  "sourceManifestSha256": source["manifestSha256"], **result}
        (temporary / "candidate.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise PreflightError("candidate output appeared during build")
        temporary.rename(output)
        return report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
