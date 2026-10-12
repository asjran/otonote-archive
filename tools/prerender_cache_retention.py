"""Audited eviction of reproducible R2 renderer inputs (Python 3.6+).

Never operates on served HTML, payloads, code, or remote objects. Current and
rollback views, pending views, both local pointers and their library pointers
pin inputs. Keep two newest inputs per region as additional rollback history.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import time

from tools.operations import AuditError, CODE, SHA256, digest, identity, render_lock, root_path, store_lock
from tools.render_retention import protected_views

RECEIPT = '.r2-materialization-receipt.json'
MANIFEST = re.compile(r'/content/releases/([a-f0-9]{24})/manifest\.json\Z')


def read_object(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024**2:
        raise AuditError('invalid_cache_control')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise AuditError('invalid_cache_control')
    return value


def pointer_ids(pointer):
    match = MANIFEST.fullmatch(pointer.get('manifest', ''))
    if pointer.get('schemaVersion') != 1 or not match or not SHA256.fullmatch(pointer.get('sha256', '')):
        raise AuditError('invalid_cache_pointer')
    result = {match[1]}
    libraries = pointer.get('libraryPointers', {})
    if not isinstance(libraries, dict) or not set(libraries) <= {'global', 'jp'}:
        raise AuditError('invalid_cache_libraries')
    for value in libraries.values():
        if value is not None:
            if not isinstance(value, dict) or 'libraryPointers' in value:
                raise AuditError('invalid_cache_libraries')
            result.update(pointer_ids(value))
    return result


def pinned_inputs(content, rendered):
    views, links = protected_views(rendered)
    controls, protected = {}, set()
    for name in ('current.json', 'jp/current.json'):
        path = content / name
        if path.parent.is_symlink():
            raise AuditError('linked_cache_pointer_parent')
        pointer = read_object(path)
        protected.update(pointer_ids(pointer))
        controls['content/' + name] = digest(path)
    for view in sorted(views):
        release = rendered / 'releases' / view
        if release.is_symlink():
            raise AuditError('linked_protected_view')
        # Without a completed pending target its exact input vector is unknown.
        # Defer cleanup instead of inferring it from the latest local pointer.
        if not release.exists():
            raise AuditError('pending_cache_references_unresolved')
        path = release / 'complete.json'
        receipt = read_object(path)
        if receipt.get('pair') != view or receipt.get('codeId') != view[:24]:
            raise AuditError('invalid_protected_receipt')
        protected.update(pointer_ids(receipt.get('pointer', {})))
        controls['rendered/' + view] = digest(path)
    return protected, {'links': links, 'controls': controls}


def inventory(release):
    receipt = read_object(release / RECEIPT)
    objects = receipt.get('objects')
    if (receipt.get('schemaVersion') != 1 or receipt.get('releaseId') != release.name
            or receipt.get('region') not in ('global', 'jp') or not isinstance(objects, dict)
            or 'manifest.json' not in objects):
        raise AuditError('invalid_cache_receipt')
    files, directories = [], []
    for path in sorted(release.rglob('*')):
        metadata = path.lstat()
        name = path.relative_to(release).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(name)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise AuditError('unsafe_cache_entry')
        checksum = digest(path)
        if name != RECEIPT and objects.get(name) != {'sha256': checksum, 'bytes': metadata.st_size}:
            raise AuditError('cache_inventory_mismatch')
        files.append({'path': name, 'sha256': checksum, 'size': metadata.st_size,
                      'inode': metadata.st_ino, 'device': metadata.st_dev,
                      'mtimeNs': metadata.st_mtime_ns, 'ctimeNs': metadata.st_ctime_ns,
                      'links': metadata.st_nlink, 'allocated': metadata.st_blocks * 512})
    if {row['path'] for row in files} != set(objects) | {RECEIPT}:
        raise AuditError('cache_inventory_mismatch')
    manifest = read_object(release / 'manifest.json')
    if (manifest.get('root') != '/content/releases/' + release.name + '/'
            or digest(release / 'manifest.json') != receipt.get('manifestSha256')):
        raise AuditError('cache_manifest_mismatch')
    return {'release': release.name, 'files': files, 'directories': directories}


def make_plan(content, rendered, cutoff):
    if type(cutoff) is not int or cutoff < 0 or cutoff > time.time() - 86400:
        raise AuditError('cache_retention_requires_one_day')
    releases = content / 'releases'
    if releases.is_symlink() or not releases.is_dir():
        raise AuditError('invalid_cache_releases')
    protected, controls = pinned_inputs(content, rendered)
    candidates = []
    for release in sorted(releases.iterdir()):
        if not CODE.fullmatch(release.name):
            # Unknown/failed staging directories require separate investigation.
            continue
        if release.is_symlink() or not release.is_dir():
            raise AuditError('invalid_cache_release')
        if not (release / RECEIPT).exists():
            continue  # Legacy inputs without provenance are never evicted.
        receipt = read_object(release / RECEIPT)
        if receipt.get('releaseId') != release.name or receipt.get('region') not in ('global', 'jp'):
            raise AuditError('invalid_cache_receipt')
        candidates.append((release, receipt['region'], release.stat().st_mtime_ns))
    for region in ('global', 'jp'):
        recent = sorted((row for row in candidates if row[1] == region), key=lambda row: row[2], reverse=True)
        protected.update(row[0].name for row in recent[:2])
    selected = [inventory(path) for path, _, modified in candidates
                if path.name not in protected and modified <= cutoff * 10**9]
    inodes = {}
    for release in selected:
        for row in release['files']:
            inodes.setdefault((row['device'], row['inode']), []).append(row)
    reclaim = sum(rows[0]['allocated'] for rows in inodes.values() if len(rows) == rows[0]['links'])
    value = {'schemaVersion': 1, 'operation': 'evict-r2-renderer-input-cache',
             'contentRoot': str(content), 'renderedRoot': str(rendered), 'cutoff': cutoff,
             'protected': sorted(protected), 'controls': controls, 'releases': selected,
             'estimatedReclaimBytes': reclaim}
    return dict(value, planId=identity(value))


def run(content, rendered, cutoff=None, expected=None):
    content, rendered = root_path(content), root_path(rendered)
    if content == rendered or content in rendered.parents or rendered in content.parents:
        raise AuditError('overlapping_cache_stores')
    with render_lock(rendered):
        with store_lock(content, '.r2-materialize.lock', 'materialization_in_progress'):
            plan = make_plan(content, rendered, expected['cutoff'] if expected is not None else cutoff)
            if expected is None:
                return plan
            if plan != expected:
                raise AuditError('cache_plan_changed_reaudit_required')
            before = os.statvfs(str(content))
            for entry in plan['releases']:
                release = content / 'releases' / entry['release']
                for row in entry['files']:
                    (release / row['path']).unlink()
                for name in sorted(entry['directories'], key=lambda item: len(Path(item).parts), reverse=True):
                    (release / name).rmdir()
                release.rmdir()
            after = os.statvfs(str(content))
            return {'status': 'evicted', 'planId': plan['planId'], 'releases': len(plan['releases']),
                    'freeBytesBefore': before.f_bavail * before.f_frsize,
                    'freeBytesAfter': after.f_bavail * after.f_frsize}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply'))
    parser.add_argument('--content', type=Path, required=True)
    parser.add_argument('--rendered', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'plan':
        result = run(args.content, args.rendered, cutoff=int(time.time()) - 86400)
        with args.plan.open('x') as output:
            json.dump(result, output, sort_keys=True)
        print(json.dumps({k: result[k] for k in ('planId', 'estimatedReclaimBytes', 'protected')}))
    else:
        print(json.dumps(run(args.content, args.rendered, expected=read_object(args.plan))))


if __name__ == '__main__':
    main()
