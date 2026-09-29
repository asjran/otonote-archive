"""Copy only bounded workflow status into the node's read-only status directory."""
import json
import os
from pathlib import Path

SOURCE = Path('/srv/ournotes-updater/app/output/global-update-workflow/latest-run.json')
TARGET = Path('/var/lib/ournotes-resource-state/latest-run.json')


def export():
    with SOURCE.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
        stamp = os.fstat(stream.fileno()).st_mtime
    if len(raw) > 1024 * 1024:
        raise ValueError('state exceeds its size limit')
    source = json.loads(raw)
    data = {'status': source.get('status', 'unknown'),
            'steps': [{'name': str(s.get('name', ''))[:80], 'status': str(s.get('status', ''))[:30]}
                      for s in source.get('steps', [])[:40] if isinstance(s, dict)]}
    if data['status'] not in ('running', 'passed', 'failed'):
        data['status'] = 'unknown'
    temporary = TARGET.with_suffix('.next')
    temporary.write_text(json.dumps(data, ensure_ascii=False))
    temporary.chmod(0o644)
    os.utime(str(temporary), (stamp, stamp))
    os.replace(str(temporary), str(TARGET))


if __name__ == '__main__':
    export()
