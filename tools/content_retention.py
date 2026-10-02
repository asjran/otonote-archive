"""Keep only published current/previous snapshots for each edition."""
from pathlib import Path
import fcntl
import re
import shutil
import time
from tools.global_remote_sync import read_json


def cleanup_content(store, *, now=None, grace_seconds=0):
    store=Path(store).resolve()
    with (store/'.publication.lock').open('a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'removedSnapshots':[],'graceSeconds':grace_seconds,'skipped':'publication_in_progress'}
        return _cleanup_content(store,now=now,grace_seconds=grace_seconds)


def _cleanup_content(store, *, now=None, grace_seconds=0):
    store=Path(store).resolve();now=time.time() if now is None else now
    if not any((store/name).is_file() for name in ('current.json','jp/current.json')):
        return {'removedSnapshots':[],'graceSeconds':grace_seconds,'skipped':'no_current_pointer'}
    protected=set()
    for name in ('current.json','previous.json','jp/current.json','jp/previous.json'):
        if (store/name).exists():
            pointer=read_json(store/name)
            match=re.fullmatch(r'/content/releases/([a-f0-9]{24})/manifest.json',pointer.get('manifest',''))
            if not match: raise ValueError('invalid retention pointer')
            target=store/'releases'/match[1]
            if target.is_symlink() or not (target/'manifest.json').is_file():
                raise ValueError('missing retention target')
            protected.add(match[1])
    owned=[]
    for path in (store/'releases').iterdir():
        if path.is_symlink() or not re.fullmatch('[a-f0-9]{24}',path.name) or not (path/'.receipt.json').is_file():continue
        manifest=read_json(path/'manifest.json')
        if manifest.get('root')!='/content/releases/'+path.name+'/':continue
        owned.append(path)
    removed=[]
    for path in owned:
        if path.name in protected or (grace_seconds>0 and now-path.stat().st_mtime<grace_seconds):continue
        shutil.rmtree(path);removed.append(path.name)
    return {'removedSnapshots':removed,'graceSeconds':grace_seconds}
