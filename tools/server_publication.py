"""Atomically publish a verified local Global candidate, preserving other apps."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from tools.global_remote_sync import file_hash, read_json, write_json
from tools.immutable_files import link_or_copy


def verify_files(site, files):
    actual = {str(p.relative_to(site)) for p in site.rglob('*') if p.is_file()}
    if actual != set(files): raise ValueError('publication file inventory differs from sealed candidate')
    for name, sha in files.items():
        path = site / name
        if site.resolve() not in path.resolve().parents or path.is_symlink() or file_hash(path) != sha:
            raise ValueError('publication file digest mismatch: ' + name)


def local_health(domain):
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', domain): raise ValueError('invalid publication domain')
    for route in ('/', '/global/zh-CN/', '/global/en/', '/global/zh-CN/music/', '/global/zh-CN/tools/live2d/'):
        subprocess.run(['curl', '--disable', '--fail', '--silent', '--show-error', '--max-time', '20',
                        '--resolve', domain + ':443:127.0.0.1', 'https://' + domain + route],
                       stdout=subprocess.DEVNULL, check=True)


def switch_link(path, target):
    temporary = path.with_name(path.name + '.next-' + uuid4().hex[:8])
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(path)


def publish(site, receipt_path, root, domain, *, health=local_health):
    site, root = Path(site).resolve(), Path(root).resolve()
    receipt = read_json(receipt_path)
    if receipt.get('validation', {}).get('status') != 'passed': raise ValueError('unverified website candidate')
    verify_files(site, receipt['files'])
    if not (root / 'releases').is_dir(): raise ValueError('publication root is not provisioned')
    if not (root / 'current').is_symlink(): raise ValueError('current must be an existing release symlink')
    identity = hashlib.sha256(json.dumps(receipt['files'], sort_keys=True).encode()).hexdigest()
    output = root / 'releases' / ('auto-' + identity[:20])
    with (root / 'update-publication.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = (root / 'current').resolve()
        if (root / 'releases') not in old.parents: raise ValueError('current release escapes configured root')
        if output == old:
            health(domain)
            return {'status': 'already_published', 'release': str(output), 'identity': identity}
        if output.exists(): raise ValueError('publication directory already exists; inspect the prior attempt')
        staging = root / 'releases' / ('.auto-' + uuid4().hex)
        try:
            shutil.copytree(site, staging, copy_function=link_or_copy)
            verify_files(staging, receipt['files'])
            # These are separately maintained products, outside the Global build.
            for relative in ('anontokyo', 'media/anontokyo'):
                source = old / relative
                if source.is_dir():
                    if (staging / relative).exists(): raise ValueError('Global candidate overlaps separately published product')
                    shutil.copytree(source, staging / relative, copy_function=link_or_copy)
            write_json(staging / '.update-release.json', {'identity': identity, 'previous': str(old), 'candidate': str(site)})
            # mkdtemp-based builds are private; expose only the sealed website.
            staging.chmod(0o755)
            for path in staging.rglob('*'):
                if path.is_symlink(): raise ValueError('symlink in publication')
                mode = 0o755 if path.is_dir() else 0o644
                if path.stat().st_mode & 0o777 != mode: path.chmod(mode)
            staging.rename(output)
            switch_link(root / 'current', output.relative_to(root))
            try:
                health(domain)
            except BaseException:
                switch_link(root / 'current', old.relative_to(root))
                # Keep the failed artifact inspectable without blocking a retry.
                output.rename(output.with_name('.failed-' + output.name + '-' + uuid4().hex[:8]))
                raise
            switch_link(root / 'previous', old.relative_to(root))
            result = {'status': 'published', 'release': str(output), 'previous': str(old), 'identity': identity}
            write_json(root / 'last-auto-update.json', result)
            return result
        finally:
            if staging.exists(): shutil.rmtree(staging)
