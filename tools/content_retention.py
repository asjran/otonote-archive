"""Bound only owned content snapshots; protect current/previous and recent tabs."""
from pathlib import Path
import re
import shutil
import time
from tools.global_remote_sync import read_json


def cleanup_content(store, *, now=None, grace_seconds=7*86400):
    store=Path(store).resolve();now=time.time() if now is None else now
    protected=set()
    for name in ('current.json','previous.json'):
        if (store/name).exists():
            pointer=read_json(store/name)
            match=re.fullmatch(r'/content/releases/([a-f0-9]{24})/manifest.json',pointer.get('manifest',''))
            if not match: raise ValueError('invalid retention pointer')
            protected.add(match[1])
    owned=[]
    for path in (store/'releases').iterdir():
        if path.is_symlink() or not re.fullmatch('[a-f0-9]{24}',path.name) or not (path/'.receipt.json').is_file():continue
        manifest=read_json(path/'manifest.json')
        if manifest.get('root')!='/content/releases/'+path.name+'/':continue
        owned.append(path)
    protected.update(p.name for p in sorted(owned,key=lambda p:p.stat().st_mtime,reverse=True)[:3])
    removed=[]
    for path in owned:
        if path.name in protected or now-path.stat().st_mtime<grace_seconds:continue
        shutil.rmtree(path);removed.append(path.name)
    return {'removedSnapshots':removed,'graceSeconds':grace_seconds}
