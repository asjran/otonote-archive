"""Bounded external trigger for the existing Actions pipeline (Python 3.6+).

This does no production work and never treats an accepted dispatch as a release.
Keep it independent of producers so its operational changes need no rebuild.
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, 'redirect refused', headers, fp)


def read_private(path, limit, credential=False):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        # The root-owned 0640 credential is readable only by the dedicated group.
        group_read = credential and info.st_uid == 0 and info.st_gid == os.getegid()
        allowed = 0o640 if group_read else 0o600
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or stat.S_IMODE(info.st_mode) & ~allowed or info.st_size > limit):
            raise ValueError('invalid private file')
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('private file too large')
        return raw


def save(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def dispatch(repository, region, token_file, state_dir, *, now=None, send=None):
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repository)
            or repository.split('/')[-1] in ('.', '..') or region not in ('global', 'jp')):
        raise ValueError('invalid dispatch target')
    directory = Path(state_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if directory.resolve() != directory or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('private state directory required')
    epoch = int(time.time() if now is None else now)
    if epoch < 0:
        raise ValueError('invalid clock')
    path = directory / (region + '.json')
    lock_fd = os.open(str(directory / (region + '.lock')), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'skipped', 'region': region, 'reason': 'already_running'}
        previous = json.loads(read_private(path, 8192)) if path.exists() else {}
        if not isinstance(previous, dict):
            raise ValueError('invalid previous state')
        attempted = previous.get('attemptEpoch')
        if attempted is not None and (type(attempted) is not int or attempted < 0):
            raise ValueError('invalid previous clock')
        if attempted is not None and attempted // 900 >= epoch // 900:
            return {'status': 'skipped', 'region': region, 'reason': 'slot_already_attempted'}
        token = read_private(Path(token_file), 4096, credential=True).decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]+', token):
            raise ValueError('invalid token')
        result = {'status': 'pending', 'region': region, 'attemptEpoch': epoch,
                  'attemptAt': datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()}
        accepted = previous.get('lastAcceptedAt')
        if isinstance(accepted, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00', accepted):
            result['lastAcceptedAt'] = accepted
        # Reserve before sending. A timeout/crash can have an unknown remote outcome;
        # do not issue a second request in this slot or replay missed slots on boot.
        save(path, result)
        request = Request('https://api.github.com/repos/' + repository + '/actions/workflows/content-r2.yml/dispatches',
                          data=json.dumps({'ref': 'main', 'inputs': {'region': region, 'mode': 'auto'}}).encode(),
                          headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                                   'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28',
                                   'User-Agent': 'OurNotes-Update-Trigger/1.0'}, method='POST')
        if send is None:
            send = build_opener(ProxyHandler({}), NoRedirect()).open
        try:
            with send(request, timeout=15) as response:
                code = response.getcode()
            if code != 204:
                result.update(status='failed', reason='unexpected_response', httpStatus=code)
            else:
                result.update(status='accepted', lastAcceptedAt=result['attemptAt'])
        except HTTPError as error:
            result.update(status='failed', reason='http_error', httpStatus=error.code)
            error.close()
        except (URLError, OSError, TimeoutError):
            result.update(status='unknown', reason='transport_failure')
        save(path, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--region', choices=('global', 'jp'), required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = dispatch(args.repository, args.region, args.token_file, args.state_dir)
    except (OSError, ValueError):
        result = {'status': 'failed', 'region': args.region, 'reason': 'local_configuration'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('accepted', 'skipped') else 2


if __name__ == '__main__':
    raise SystemExit(main())
