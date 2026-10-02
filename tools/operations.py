"""Offline audit and lossless deduplication of immutable render/code assets.

No production defaults. Actual paths/configuration stay outside version control.
Deduplication preserves every URL, byte and release; it never removes releases.
Compatible with Python 3.6+ for maintenance hosts; no third-party dependencies.
"""
import argparse
import collections
import contextlib
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid


PAIR = re.compile(r'^[a-f0-9]{24}-[a-f0-9]{24}$')
PAYLOAD = re.compile(r'^([a-f0-9]{64})\.json$')
CODE = re.compile(r'^[a-f0-9]{24}$')
SHA256 = re.compile(r'^[a-f0-9]{64}$')


class AuditError(ValueError):
    """Fixed error codes only: never embed private paths or file contents."""


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def attribute_identity(path):
    """Include ACL/security labels without exposing their values in reports."""
    if not hasattr(os, 'listxattr') or not hasattr(os, 'getxattr'):
        if sys.platform == 'darwin':
            try:
                names = subprocess.check_output(['/usr/bin/xattr', str(path)], stderr=subprocess.DEVNULL).decode().splitlines()
                return identity([(name, hashlib.sha256(subprocess.check_output(
                    ['/usr/bin/xattr', '-px', name, str(path)], stderr=subprocess.DEVNULL)).hexdigest()) for name in sorted(names)])
            except (OSError, ValueError, subprocess.CalledProcessError):
                raise AuditError('extended_attribute_check_failed')
        raise AuditError('extended_attribute_check_unavailable')
    try:
        attrs = [(name, hashlib.sha256(os.getxattr(str(path), name)).hexdigest())
                 for name in sorted(os.listxattr(str(path)))]
    except OSError as error:
        if error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
            return identity([])
        raise AuditError('extended_attribute_check_failed')
    return identity(attrs)


def root_path(value):
    path = Path(value).absolute()
    if path.is_symlink() or not path.is_dir():
        raise AuditError('invalid_store_root')
    return path.resolve()


def safe_file(root, relative):
    parts = Path(relative).parts
    if len(parts) != 4 or parts[0] != 'releases' or not PAIR.fullmatch(parts[1]) or parts[2] != 'payloads' or not PAYLOAD.fullmatch(parts[3]):
        raise AuditError('invalid_payload_path')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise AuditError('linked_payload_path')
    if not path.is_file():
        raise AuditError('missing_payload')
    return path


@contextlib.contextmanager
def store_lock(root, name, busy):
    path = root / name
    if path.is_symlink():
        raise AuditError('linked_lock')
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AuditError(busy)
        yield
    finally:
        os.close(fd)


def render_lock(root):
    return store_lock(root, '.render.lock', 'render_in_progress')


def code_lock(root):
    return store_lock(root, '.publication.lock', 'code_publication_in_progress')


def file_record(root, path, expected):
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise AuditError('nonregular_asset')
    return {'path':path.relative_to(root).as_posix(), 'sha256':expected,
            'device':metadata.st_dev, 'inode':metadata.st_ino, 'size':metadata.st_size,
            'mtimeNs':metadata.st_mtime_ns, 'mode':stat.S_IMODE(metadata.st_mode),
            'uid':metadata.st_uid, 'gid':metadata.st_gid, 'links':metadata.st_nlink,
            'attributes':attribute_identity(path), 'flags':getattr(metadata, 'st_flags', 0),
            'allocated':metadata.st_blocks * 512}


def inventory(root):
    releases = root / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise AuditError('invalid_releases_directory')
    files = []
    skipped = 0
    for release in sorted(releases.iterdir()):
        if not PAIR.fullmatch(release.name):
            skipped += 1
            continue
        if release.is_symlink():
            raise AuditError('linked_release')
        marker = release / 'complete.json'
        if marker.is_symlink() or not marker.is_file():
            raise AuditError('missing_release_receipt')
        try:
            receipt = json.loads(marker.read_text())
        except (ValueError, OSError):
            raise AuditError('invalid_release_receipt')
        if not isinstance(receipt, dict):
            raise AuditError('invalid_release_receipt')
        if receipt.get('pair') != release.name or receipt.get('codeId') != release.name[:24]:
            raise AuditError('release_identity_mismatch')
        payloads = release / 'payloads'
        if payloads.is_symlink():
            raise AuditError('linked_payload_directory')
        if not payloads.exists():
            continue
        for path in sorted(payloads.iterdir()):
            match = PAYLOAD.fullmatch(path.name)
            if not match:
                skipped += 1
                continue
            relative = path.relative_to(root).as_posix()
            path = safe_file(root, relative)
            if digest(path) != match.group(1):
                raise AuditError('payload_digest_mismatch')
            files.append(file_record(root, path, match.group(1)))
    return files, skipped


def safe_code_file(root, relative):
    if not isinstance(relative, str) or '\\' in relative or '\x00' in relative:
        raise AuditError('invalid_code_asset_path')
    parts = relative.split('/')
    if len(parts) < 4 or parts[0] != 'releases' or not CODE.fullmatch(parts[1]) or parts[2] != 'compiled' or any(part in ('', '.', '..') for part in parts):
        raise AuditError('invalid_code_asset_path')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise AuditError('linked_code_asset_path')
    if not path.is_file():
        raise AuditError('missing_code_asset')
    return path


def read_code_receipt(path):
    if path.is_symlink() or not path.is_file():
        raise AuditError('invalid_code_receipt')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuditError('invalid_code_receipt')
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError):
        raise AuditError('invalid_code_receipt')
    if not isinstance(value, dict):
        raise AuditError('invalid_code_receipt')
    return value


def normalize_excluded_code_ids(values):
    if not isinstance(values, (list, tuple, set, frozenset)) or any(
        not isinstance(value, str) or not CODE.fullmatch(value) for value in values
    ):
        raise AuditError('invalid_excluded_code_id')
    return tuple(sorted(set(values)))


def code_inventory(root, exclude_code_ids=()):
    excluded = normalize_excluded_code_ids(exclude_code_ids)
    releases = root / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise AuditError('invalid_releases_directory')
    files, preserved, skipped = [], [], 0
    for release in sorted(releases.iterdir()):
        # An explicit exclusion is an untouched version, not a relaxed receipt
        # check. Do not stat, traverse, read or select any path in that version.
        if release.name in excluded:
            continue
        if not CODE.fullmatch(release.name):
            skipped += 1
            continue
        if release.is_symlink() or not release.is_dir():
            raise AuditError('invalid_code_release')
        marker = release / 'code-release.json'
        metadata = read_code_receipt(marker)
        declared = metadata.get('files')
        if metadata.get('schemaVersion') != 1 or metadata.get('contentSchemaVersion') != 1 or not isinstance(declared, dict) or not declared:
            raise AuditError('invalid_code_contract')
        # Match verify_code/build_web_client: insertion order of the serialized
        # manifest inventory is part of the existing codeId contract.
        calculated = hashlib.sha256(json.dumps(declared, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
        if metadata.get('codeId') != release.name or calculated != release.name:
            raise AuditError('code_identity_mismatch')
        compiled = release / 'compiled'
        if compiled.is_symlink() or not compiled.is_dir():
            raise AuditError('invalid_compiled_directory')
        actual = set()
        for directory, dirs, names in os.walk(str(compiled), followlinks=False):
            for name in dirs + names:
                path = Path(directory) / name
                if path.is_symlink():
                    raise AuditError('linked_code_asset_path')
                if name in names:
                    if name == '.DS_Store':
                        skipped += 1
                    else:
                        actual.add(path.relative_to(compiled).as_posix())
        if actual != set(declared):
            raise AuditError('code_inventory_mismatch')
        for name, expected in declared.items():
            if not isinstance(expected, str) or not SHA256.fullmatch(expected):
                raise AuditError('invalid_code_asset_digest')
            path = safe_code_file(root, 'releases/' + release.name + '/compiled/' + name)
            if not stat.S_ISREG(path.stat().st_mode):
                raise AuditError('nonregular_asset')
            if digest(path) != expected:
                raise AuditError('code_asset_digest_mismatch')
            if path.name in ('index.html', 'code-release.json', 'verification.json', 'entry-shell.json'):
                preserved.append({'path':path.relative_to(root).as_posix(), 'sha256':expected})
            else:
                files.append(file_record(root, path, expected))
        shell_path = release / 'index.html'
        if shell_path.is_symlink() or not shell_path.is_file():
            raise AuditError('invalid_code_shell')
        try:
            shell = shell_path.read_text()
        except (OSError, UnicodeError):
            raise AuditError('invalid_code_shell')
        boot = re.search(r'src="/app/releases/' + release.name + r'/(boot-[A-Z0-9]+\.js)"', shell)
        if not boot or boot.group(1) not in declared:
            raise AuditError('invalid_code_shell')
        if 'entry-shell.json' in declared:
            entry = read_code_receipt(compiled / 'entry-shell.json')
            if entry.get('sha256') != hashlib.sha256(shell.replace(release.name, '__CODE_ID__').encode()).hexdigest():
                raise AuditError('code_shell_digest_mismatch')
        for path in (marker, shell_path, release / 'verification.json'):
            if path.is_symlink():
                raise AuditError('linked_code_receipt')
            if path.name != 'verification.json' or path.exists():
                if not path.is_file():
                    raise AuditError('invalid_code_receipt')
                preserved.append({'path':path.relative_to(root).as_posix(), 'sha256':digest(path)})
    return files, skipped, preserved


def deduplication_plan(files, skipped, *, operation='deduplicate-render-payloads', preserved=None):
    groups = collections.defaultdict(list)
    for item in files:
        # Do not change ownership, permissions or filesystem of any file.
        key = (item['sha256'], item['device'], item['mode'], item['uid'], item['gid'], item['attributes'], item['flags'])
        groups[key].append(item)
    actions = []
    reclaim = 0
    for members in groups.values():
        canonical = members[0]
        old_inodes = collections.defaultdict(list)
        for item in members[1:]:
            if item['inode'] == canonical['inode']:
                continue
            actions.append({'source':canonical['path'], 'target':item['path'], 'sha256':item['sha256']})
            old_inodes[item['inode']].append(item)
        for items in old_inodes.values():
            if len(items) == items[0]['links']:
                reclaim += items[0]['allocated']
    body = {'schemaVersion':1, 'operation':operation,
            'inventoryDigest':identity(files if preserved is None else {'assets':files, 'preserved':preserved}), 'actions':actions,
            'payloadFiles' if preserved is None else 'assetFiles':len(files), 'skippedUnknown':skipped,
            'estimatedReclaimBytes':reclaim}
    return dict(body, planId=identity(body))


def make_plan(root):
    files, skipped = inventory(root)
    return deduplication_plan(files, skipped)


def make_code_plan(root, exclude_code_ids=()):
    excluded = normalize_excluded_code_ids(exclude_code_ids)
    files, skipped, preserved = code_inventory(root, excluded)
    plan = deduplication_plan(files, skipped, operation='deduplicate-code-assets', preserved=preserved)
    # Empty exclusions preserve the exact legacy plan shape and digest.
    if excluded:
        body = {key:value for key,value in plan.items() if key != 'planId'}
        body['excludedCodeIds'] = list(excluded)
        plan = dict(body, planId=identity(body))
    return plan


def plan_deduplication(value):
    root = root_path(value)
    with render_lock(root):
        return make_plan(root)


def apply_deduplication(value, expected):
    return apply_plan(value, expected, render_lock, make_plan, safe_file)


def plan_code_deduplication(value, exclude_code_ids=()):
    excluded = normalize_excluded_code_ids(exclude_code_ids)
    root = root_path(value)
    with code_lock(root):
        return make_code_plan(root, excluded)


def apply_code_deduplication(value, expected, exclude_code_ids=()):
    excluded = normalize_excluded_code_ids(exclude_code_ids)
    if not isinstance(expected, dict):
        raise AuditError('invalid_deduplication_plan')
    if normalize_excluded_code_ids(expected.get('excludedCodeIds', ())) != excluded:
        raise AuditError('plan_changed_reaudit_required')
    return apply_plan(value, expected, code_lock,
                      lambda root: make_code_plan(root, excluded), safe_code_file)


def apply_plan(value, expected, lock, planner, resolve_file):
    root = root_path(value)
    with lock(root):
        current = planner(root)
        if expected != current:
            raise AuditError('plan_changed_reaudit_required')
        before = os.statvfs(str(root))
        changed = 0
        for action in current['actions']:
            source = resolve_file(root, action['source'])
            target = resolve_file(root, action['target'])
            # Both were hashed under the publication lock; ensure the selected
            # canonical file still satisfies its content-addressed identity.
            if digest(source) != action['sha256'] or digest(target) != action['sha256']:
                raise AuditError('payload_changed_during_apply')
            temporary = target.parent / ('.dedupe-' + uuid.uuid4().hex)
            try:
                os.link(str(source), str(temporary))
                os.replace(str(temporary), str(target))
                changed += 1
            finally:
                if temporary.exists():
                    temporary.unlink()
        after = os.statvfs(str(root))
        return {'status':'complete', 'planId':current['planId'], 'linkedFiles':changed,
                'freeBytesBefore':before.f_bavail * before.f_frsize,
                'freeBytesAfter':after.f_bavail * after.f_frsize,
                'preserved':'all_release_paths_and_bytes'}


def task_status(report, last_success=None):
    """Public operational summary from private reports; never echo raw errors."""
    error = str(report.get('error', ''))
    if 'insufficient free disk' in error:
        reason = 'disk_capacity_blocked'
    elif error == 'game_rpc_unknown':
        reason = 'upstream_rpc_unknown'
    elif report.get('status') == 'failed':
        reason = 'task_failed'
    else:
        reason = None
    return {'status':report.get('status') if report.get('status') in ('failed','complete','passed','running','unchanged') else 'unknown',
            'reason':reason, 'paused':bool(report.get('paused',False)),
            'hasLastSuccess':bool(last_success)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    for command in ('dedupe-plan', 'dedupe-apply'):
        child = sub.add_parser(command)
        roots = child.add_mutually_exclusive_group(required=True)
        roots.add_argument('--rendered-root')
        roots.add_argument('--code-root')
        child.add_argument('--plan', required=True, type=Path)
        child.add_argument('--exclude-code-id', action='append', default=[],
                           help='leave this 24-hex code version untouched; repeat on both plan and apply')
    args = parser.parse_args(argv)
    try:
        if getattr(args, 'exclude_code_id', None) and not args.code_root:
            raise AuditError('code_exclusions_require_code_root')
        if args.command == 'dedupe-plan':
            result = plan_code_deduplication(args.code_root, args.exclude_code_id) if args.code_root else plan_deduplication(args.rendered_root)
            fd = os.open(str(args.plan), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(result, stream, sort_keys=True, indent=2)
            print(json.dumps({k:v for k,v in result.items() if k != 'actions'}))
        elif args.command == 'dedupe-apply':
            expected = json.loads(args.plan.read_text())
            print(json.dumps(apply_code_deduplication(args.code_root, expected, args.exclude_code_id) if args.code_root else apply_deduplication(args.rendered_root, expected)))
        else:
            parser.error('command required')
    except AuditError as error:
        print(json.dumps({'status':'blocked','reason':str(error)}), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'status':'blocked','reason':'invalid_input_or_io_failure'}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
