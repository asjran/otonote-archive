"""Build a complete isolated Global website candidate with one command."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_candidates import build_candidates
from tools.release_preflight import PreflightError, inspect_plan
from tools.release_site import build_site


def build_release(plan: Path, output: Path, *, root=ROOT):
    # Keep orchestration outputs away from source trees and existing previews.
    output_root = (root / 'output').resolve()
    if output.exists() or output.is_symlink():
        raise PreflightError('build output already exists; choose a new directory')
    output = output.resolve()
    if output_root not in output.parents:
        raise PreflightError('build output must be a new directory under repository output/')
    readiness = inspect_plan(plan, root=root, require_production=True)
    if readiness['status'] != 'passed':
        raise PreflightError('Global inputs are not ready; run catalog:preflight for details.')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}-', dir=output.parent))
    try:
        candidate = build_candidates(plan, stage / 'candidate', root=root,
                                     locales=('zh-CN', 'en'))
        validation = build_site(stage / 'candidate', stage / 'site')
        report = {
            'schemaVersion': 1, 'status': 'built', 'historicalReplay': False,
            'publicationReady': False, 'inputPlanSha256': candidate['inputPlanSha256'],
            'candidatePath': 'candidate', 'sitePath': 'site', 'validation': validation,
            'limitations': json.loads((stage / 'site/site-candidate.json').read_text())['limitations'],
        }
        (stage / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        if output.exists():
            raise PreflightError('build output appeared during generation')
        stage.rename(output)
        return {**report, 'output': str(output)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    plan = args.plan or ROOT / 'config' / 'release-inputs.json'
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    output = args.output or ROOT / 'output/release-builds' / name
    try:
        print(json.dumps(build_release(plan, output), ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Release build failed: {exc}\n')


if __name__ == '__main__':
    main()
