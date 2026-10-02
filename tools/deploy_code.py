"""Upload an already verified candidate using private, external deployment settings."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
from tools.code_publication import verify_code


def load_config(path):
    path=Path(path).resolve()
    root=Path(__file__).resolve().parents[1]
    if path == root or root in path.parents: raise ValueError('deployment settings must be outside the source checkout')
    if stat.S_IMODE(path.stat().st_mode)&0o077: raise ValueError('deployment settings must have owner-only permissions')
    config=json.loads(path.read_text())
    keys={'sshHost','codeRoot','runtimeRoot','python','runtimeSha256','healthUrl','healthContains'}
    if set(config)!=keys: raise ValueError('deployment settings have missing or unknown fields')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*',config['sshHost']): raise ValueError('invalid SSH target')
    for key in ('codeRoot','runtimeRoot','python'):
        value=config[key]
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in Path(value).parts:
            raise ValueError('invalid deployment path')
    if not re.fullmatch('[a-f0-9]{64}',config['runtimeSha256']): raise ValueError('invalid runtime digest')
    from urllib.parse import urlparse
    url=urlparse(config['healthUrl'])
    if url.scheme not in ('http','https') or not url.netloc or url.username or url.password or url.query:
        raise ValueError('invalid health URL')
    if not config['healthContains']: raise ValueError('health check must match an expected response')
    return config


RUNTIME_BOOTSTRAP = r"""import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
raw=(root/'runtime.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=sys.argv[2]:raise SystemExit('runtime manifest mismatch')
manifest=json.loads(raw)
actual={}
for path in root.rglob('*'):
    if path.is_symlink():raise SystemExit('linked runtime entry')
    if path.is_file() and path.relative_to(root).as_posix()!='runtime.json':
        actual[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
if manifest.get('schemaVersion')!=1 or actual!=manifest.get('files'):raise SystemExit('runtime inventory mismatch')
"""


def run(command, *, input_data=None):
    result=subprocess.run(command,capture_output=True,input=input_data)
    if result.returncode: raise ValueError('deployment command failed; inspect protected server logs')
    return result.stdout


def deploy(source, config, receipt_sha, expected_current, dry_run=False):
    if not re.fullmatch('[a-f0-9]{64}',receipt_sha): raise ValueError('invalid reviewed receipt digest')
    if expected_current != 'none' and not re.fullmatch('[a-f0-9]{24}',expected_current): raise ValueError('invalid expected current code')
    identity,_=verify_code(source,require_verified=True,expected_receipt_sha256=receipt_sha)
    result={'codeId':identity,'verificationSha256':receipt_sha,'status':'prepared' if dry_run else 'published'}
    if dry_run: return result
    host=config['sshHost']; incoming=config['codeRoot']+'/incoming/'+identity
    def ssh(arguments): return run(['ssh','--',host,shlex.join(arguments)])
    launcher='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("tools.code_publication",run_name="__main__")'
    env=[config['python'],'-I','-B','-c',launcher,config['runtimeRoot']]
    # Runtime verification happens before a candidate is uploaded or activated.
    bootstrap=[config['python'],'-I','-',config['runtimeRoot'],config['runtimeSha256']]
    run(['ssh','--',host,shlex.join(bootstrap)],input_data=RUNTIME_BOOTSTRAP.encode())
    ssh(['mkdir','-p','--',incoming])
    # Host and destination were restricted to shell-safe characters above;
    # avoid --protect-args, unavailable in macOS's bundled openrsync.
    run(['rsync','-r','--checksum','--exclude=.DS_Store','--',str(Path(source).resolve())+'/',host+':'+incoming+'/'])
    output=ssh(env+['--source',incoming,'--root',config['codeRoot'],
                    '--require-verified','--expected-receipt-sha256',receipt_sha,'--expected-current',expected_current,
                    '--health-url',config['healthUrl'],'--health-contains',config['healthContains']])
    try: published=json.loads(output)
    except (ValueError,UnicodeDecodeError): raise ValueError('unexpected deployment response') from None
    if published.get('codeId')!=identity or published.get('status') not in ('code_published','unchanged'):
        raise ValueError('deployment acknowledgement mismatch')
    result['status']=published['status'];return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--receipt-sha256',required=True);p.add_argument('--expected-current',required=True)
    p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    try: print(json.dumps(deploy(a.source,load_config(a.config),a.receipt_sha256,a.expected_current,a.dry_run)))
    except (OSError,ValueError,KeyError,TypeError) as e:
        print(json.dumps({'error':str(e) if isinstance(e,ValueError) and not isinstance(e,json.JSONDecodeError) else type(e).__name__}),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
