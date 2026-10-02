"""Verify and atomically install an existing frontend candidate without rebuilding."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import urlopen
from urllib.parse import urlparse
from tools.content_publication import verify_tree
from tools.global_remote_sync import read_json


def verify_code(source, *, require_verified=False, expected_receipt_sha256=None):
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
    if 'entry-shell.json' in files:
        shell_hash = hashlib.sha256(shell.replace(identity,'__CODE_ID__').encode()).hexdigest()
        if read_json(source/'compiled/entry-shell.json').get('sha256') != shell_hash:
            raise ValueError('code shell digest mismatch')
    expected = {'compiled/'+p:h for p,h in files.items()}
    for name in ('index.html','code-release.json'): expected[name] = hashlib.sha256((source/name).read_bytes()).hexdigest()
    receipt = source/'verification.json'
    if receipt.exists():
        from tools.release_candidate import validate_receipt
        validate_receipt(source, metadata, read_json(receipt), expected_receipt_sha256)
        expected['verification.json'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    elif require_verified or expected_receipt_sha256:
        raise ValueError('missing verification receipt; preview releases cannot be deployed')
    if require_verified and 'entry-shell.json' not in files: raise ValueError('missing shell integrity record')
    verify_tree(source,expected)
    return identity, expected


def _pointer(root, name):
    pointer = root/name
    if not pointer.is_symlink():
        if pointer.exists(): raise ValueError(name+' code must be a symlink')
        return None
    target = os.readlink(pointer)
    if not re.fullmatch(r'releases/[a-f0-9]{24}', target) or not pointer.is_dir():
        raise ValueError('unsafe or missing '+name+' code target')
    return target


def _switch(root, name, target):
    if target is None:
        (root/name).unlink(missing_ok=True); return
    temporary = root/('.'+name+'.next')
    temporary.unlink(missing_ok=True); temporary.symlink_to(target); os.replace(temporary,root/name)


def publish_code(source, root, *, expected_current=None, require_verified=False,
                 expected_receipt_sha256=None, health_check=None):
    source, root = Path(source).resolve(), Path(root).resolve()
    if source == root or source in root.parents or (root in source.parents and source.parent != root/'incoming'):
        raise ValueError('code store overlaps source outside incoming directory')
    identity, expected = verify_code(source, require_verified=require_verified, expected_receipt_sha256=expected_receipt_sha256)
    if (root/'releases').is_symlink(): raise ValueError('linked code release store')
    (root/'releases').mkdir(parents=True,exist_ok=True)
    with (root/'.publication.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old = _pointer(root,'current')
        previous = _pointer(root,'previous')
        current_id = old.split('/')[-1] if old else 'none'
        if expected_current is not None and expected_current != current_id:
            raise ValueError('current code changed since deployment was prepared')
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
        target = 'releases/'+identity
        changed = old != target
        try:
            if changed:
                if old is not None: _switch(root,'previous',old)
                _switch(root,'current',target)
            if health_check is not None and health_check(identity) is not True:
                raise ValueError('code health check failed')
        except Exception:
            if changed:
                _switch(root,'current',old); _switch(root,'previous',previous)
            raise ValueError('code health check failed; previous pointers restored') from None
        return {'status':'code_published' if changed else 'unchanged','codeId':identity,'contentSchemaVersion':1,
                'previousCodeId':current_id,'healthChecked':health_check is not None}


def http_health(url_template, expected_text, identity):
    url = url_template.replace('{codeId}',identity)
    parsed = urlparse(url)
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password: raise ValueError('invalid health URL')
    with urlopen(url, timeout=15) as response:
        return response.status == 200 and expected_text.replace('{codeId}',identity).encode() in response.read(1024*1024)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path)
    p.add_argument('--verify-only',action='store_true');p.add_argument('--require-verified',action='store_true')
    p.add_argument('--expected-receipt-sha256');p.add_argument('--expected-current')
    p.add_argument('--health-url');p.add_argument('--health-contains',default='{codeId}')
    args=p.parse_args()
    if not args.verify_only and not args.root: p.error('--root is required for publication')
    if not args.verify_only and (not args.require_verified or not args.expected_receipt_sha256):
        p.error('publication requires --require-verified and a reviewed --expected-receipt-sha256')
    if args.expected_receipt_sha256 and not re.fullmatch('[a-f0-9]{64}',args.expected_receipt_sha256): p.error('invalid receipt digest')
    options = {'require_verified':args.require_verified,'expected_receipt_sha256':args.expected_receipt_sha256}
    try:
        if args.verify_only: result={'codeId':verify_code(args.source,**options)[0]}
        else:
            health = (lambda identity:http_health(args.health_url,args.health_contains,identity)) if args.health_url else None
            result=publish_code(args.source,args.root,expected_current=args.expected_current,health_check=health,**options)
        print(json.dumps(result,ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Raw OS/HTTP messages may contain deployment paths, hosts or credentials.
        print(json.dumps({'error':str(error) if isinstance(error,ValueError) else type(error).__name__})); return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
