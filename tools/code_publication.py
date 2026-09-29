"""Install a locally compiled frontend; never upload or replace game content."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from tools.content_publication import inventory, verify_tree
from tools.global_remote_sync import read_json


def verify_code(source):
    source = Path(source).resolve()
    metadata = read_json(source/'code-release.json')
    if metadata.get('schemaVersion') != 1 or metadata.get('contentSchemaVersion') != 1: raise ValueError('unsupported code contract')
    identity = metadata['codeId']
    if not re.fullmatch('[a-f0-9]{24}',identity): raise ValueError('unsafe code identity')
    files = metadata['files']
    if hashlib.sha256(json.dumps(files,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24] != identity:
        raise ValueError('code identity mismatch')
    verify_tree(source/'compiled',files)
    shell = (source/'index.html').read_text()
    if not re.search(r'src="/app/releases/'+identity+r'/boot-[A-Z0-9]+\.js"',shell): raise ValueError('invalid code shell')
    expected = {'compiled/'+p:h for p,h in files.items()}
    for name in ('index.html','code-release.json'): expected[name] = hashlib.sha256((source/name).read_bytes()).hexdigest()
    verify_tree(source,expected)
    return identity, expected


def publish_code(source, root):
    source, root = Path(source).resolve(), Path(root).resolve()
    if source == root or source in root.parents or (root in source.parents and source.parent != root/'incoming'):
        raise ValueError('code store overlaps source outside incoming directory')
    identity, expected = verify_code(source)
    (root/'releases').mkdir(parents=True,exist_ok=True)
    with (root/'.publication.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        final = root/'releases'/identity
        if final.is_symlink(): raise ValueError('linked code release')
        if not final.exists():
            stage = Path(tempfile.mkdtemp(prefix='.code-',dir=root/'releases'))
            try:
                shutil.copytree(source,stage,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.DS_Store'))
                verify_tree(stage,expected)
                stage.chmod(0o755)
                stage.rename(final)
            finally:
                if stage.exists(): shutil.rmtree(stage)
        verify_tree(final,expected)
        current=root/'current'
        if current.exists() and not current.is_symlink(): raise ValueError('current code must be a symlink')
        if current.is_symlink() and current.resolve()==final: return {'status':'unchanged','codeId':identity}
        def switch(name,target):
            tmp=root/('.'+name+'.next');tmp.unlink(missing_ok=True);tmp.symlink_to(target);os.replace(tmp,root/name)
        if current.is_symlink(): switch('previous',os.readlink(current))
        switch('current','releases/'+identity)
        return {'status':'code_published','codeId':identity,'contentSchemaVersion':1}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path)
    p.add_argument('--verify-only',action='store_true')
    args=p.parse_args()
    if not args.verify_only and not args.root: p.error('--root is required for publication')
    print(json.dumps({'codeId':verify_code(args.source)[0]} if args.verify_only else publish_code(args.source,args.root),ensure_ascii=False))
