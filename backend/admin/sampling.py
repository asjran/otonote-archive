"""Bounded local log ingestion and counter sampling; never runs shell commands."""
import datetime as dt
import json
import re
import time
import urllib.request
from pathlib import Path

from tools.monitor.collect import classify
from .config import loopback_url
from .transport import NoRedirect


def read_nginx(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(loopback_url(url), timeout=1) as response:
        text = response.read(2048).decode('ascii')
    active = re.search(r'Active connections:\s*(\d+)', text)
    counters = re.search(r'^\s*(\d+)\s+(\d+)\s+(\d+)\s*$', text, re.M)
    states = re.search(r'Reading:\s*(\d+)\s+Writing:\s*(\d+)\s+Waiting:\s*(\d+)', text)
    if not (active and counters and states):
        raise ValueError('invalid nginx status')
    return dict(zip(('active', 'requests', 'reading', 'writing', 'waiting'),
                    [int(active[1]), int(counters[3]), *map(int, states.groups())]))


def read_network(interfaces, root=Path('/sys/class/net')):
    if not interfaces:
        raise ValueError('no network interfaces configured')
    values = {'rx': 0, 'tx': 0}
    identities = []
    for interface in interfaces:
        base = root / interface
        identities.append((interface, (base / 'ifindex').read_text().strip()))
        for direction in values:
            values[direction] += int((base / 'statistics' / (direction + '_bytes')).read_text())
    return {**values, 'identity': identities}


class Sampler:
    def __init__(self, config, network_reader=read_network, nginx_reader=read_nginx):
        self.config = config
        self.network_reader, self.nginx_reader = network_reader, nginx_reader
        self.previous = None

    def sample(self, now=None, monotonic=None):
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic
        current = {'ts': now, 'clock': monotonic, 'nginx': None, 'network': None}
        sample = {'ts': now, 'elapsed': 0, 'active': None, 'reading': None, 'writing': None, 'waiting': None,
                  'rps': None, 'rxMbps': None, 'txMbps': None, 'rxBytes': None, 'txBytes': None,
                  'nginxState': 'not_configured', 'networkState': 'not_configured', 'gap': True,
                  'rxLimitMbps': self.config.get('rxLimitMbps'), 'txLimitMbps': self.config.get('txLimitMbps')}
        if self.config.get('statusUrl'):
            try:
                current['nginx'] = self.nginx_reader(self.config['statusUrl'])
                sample.update({k: current['nginx'][k] for k in ('active', 'reading', 'writing', 'waiting')})
                sample['nginxState'] = 'ok'
            except (OSError, ValueError, KeyError):
                sample['nginxState'] = 'unavailable'
        if self.config.get('interfaces'):
            try:
                current['network'] = self.network_reader(self.config['interfaces'])
                sample['networkState'] = 'ok'
            except (OSError, ValueError):
                sample['networkState'] = 'unavailable'
        previous = self.previous
        if previous:
            elapsed = monotonic - previous['clock']
            if 0 < elapsed <= 3 * self.config.get('sampleSeconds', 5) and abs((now - previous['ts']) - elapsed) < 2:
                sample.update(elapsed=elapsed, gap=False)
                if previous['nginx'] and current['nginx']:
                    delta = current['nginx']['requests'] - previous['nginx']['requests']
                    if delta >= 0:
                        sample['rps'] = delta / elapsed
                a, b = previous['network'], current['network']
                if a and b and a['identity'] == b['identity'] and all(b[k] >= a[k] for k in ('rx', 'tx')):
                    for direction in ('rx', 'tx'):
                        delta = b[direction] - a[direction]
                        sample[direction + 'Bytes'] = delta
                        sample[direction + 'Mbps'] = delta * 8 / elapsed / 1_000_000
        self.previous = current
        return sample


def ingest_log(store, site, now=None, limit=2000):
    now = time.time() if now is None else now
    if not site.get('accessLog'):
        return
    path = Path(site['accessLog'])
    sid = site['id']
    try:
        stat = path.stat()
    except OSError:
        store.set_state('log:' + sid, {'status': 'unavailable', 'checkedAt': now})
        return
    store.ensure_capacity()
    allowed = set(site.get('paths', [])) | set(site.get('resources', []))
    with store.transaction() as db:
        checkpoint = store.state('offset:' + sid, {}, db)
        identity = f'{stat.st_dev}:{stat.st_ino}'
        files = []
        if checkpoint.get('identity') and checkpoint['identity'] != identity:
            old = path.with_name(path.name + '.1')
            if old.exists():
                s = old.stat()
                if f'{s.st_dev}:{s.st_ino}' == checkpoint['identity']:
                    files.append((old, checkpoint.get('offset', 0), checkpoint['identity']))
            if not files:
                store.set_state('logGap:' + sid, now, db)
        offset = checkpoint.get('offset', 0) if checkpoint.get('identity') == identity else 0
        if offset > stat.st_size:
            offset = 0
            store.set_state('logGap:' + sid, now, db)
        files.append((path, offset, identity))
        processed, invalid = 0, 0
        for filename, offset, file_identity in files:
            with filename.open('rb') as stream:
                stream.seek(offset)
                while processed + invalid < limit:
                    position = stream.tell()
                    line = stream.readline(65537)
                    if not line:
                        break
                    if not line.endswith(b'\n') and len(line) <= 65536:
                        stream.seek(position)
                        break
                    try:
                        if len(line) > 65536:
                            raise ValueError('oversize log line')
                        item = json.loads(line)
                        timestamp = dt.datetime.fromisoformat(item['time'].replace('Z', '+00:00'))
                        if timestamp.tzinfo is None:
                            raise ValueError('missing timezone')
                        ts = timestamp.timestamp()
                        if not now - 366 * 86400 <= ts <= now + 60:
                            raise ValueError('invalid timestamp')
                        route = str(item.get('path', '/')).split('?', 1)[0].split('#', 1)[0]
                        status, size = int(item['status']), int(item.get('bytes', 0))
                        if not 100 <= status <= 599 or not 0 <= size <= 10 ** 13:
                            raise ValueError('invalid log value')
                        category = classify(route, str(item.get('content_type', '')), str(item.get('user_agent', '')))
                        if category not in {'synthetic', 'health'}:
                            route = route if route in allowed else '(unmatched)'
                            db.execute('''INSERT INTO traffic VALUES(?,?,?,?,?,1,?)
                                ON CONFLICT(site,minute,path,category,status) DO UPDATE SET
                                requests=requests+1, bytes=bytes+excluded.bytes''',
                                (sid, int(ts) // 60 * 60, route, category, status, size))
                        processed += 1
                    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                        invalid += 1
                store.set_state('offset:' + sid, {'identity': file_identity, 'offset': stream.tell()}, db)
                if processed + invalid >= limit:
                    break
        store.set_state('log:' + sid, {'status': 'ok', 'checkedAt': now, 'processed': processed,
                                      'invalid': invalid, 'gapAt': store.state('logGap:' + sid, db=db)}, db)
