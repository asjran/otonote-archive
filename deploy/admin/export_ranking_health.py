"""Expose only ranking health fields to the unprivileged sampler (Python 3.6)."""
import json
import os
from pathlib import Path
import tempfile


def export(source, target):
    source, target = Path(source), Path(target)
    value = {'status': 'unavailable'}
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 16384:
            raise ValueError('unsafe ranking sample')
        with source.open('rb') as handle:
            raw = handle.read(16385)
        if len(raw) > 16384:
            raise ValueError('oversized ranking sample')
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get('status') not in ('complete', 'waiting', 'failed', 'running', 'paused')
                or type(data.get('paused')) is not bool or not isinstance(data.get('observedAt'), str)
                or len(data['observedAt']) > 64):
            raise ValueError('invalid ranking sample')
        value = {name: data[name] for name in ('status', 'paused', 'observedAt')}
    except (OSError, ValueError, TypeError):
        pass
    descriptor, temporary = tempfile.mkstemp(prefix='.ranking-health-', dir=str(target.parent))
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, separators=(',', ':'))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, str(target))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    export('/var/lib/ournotes-rankings-capture/status.json',
           '/var/lib/ournotes-resource-state/ranking-health.json')
