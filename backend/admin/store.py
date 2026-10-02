"""Transactional event, traffic and sampled-load storage, separate from resources."""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def day_key(ts, timezone):
    return dt.datetime.fromtimestamp(ts, ZoneInfo(timezone)).strftime("%Y-%m-%d")


def window_start(window, timezone, now):
    date = dt.datetime.fromtimestamp(now, ZoneInfo(timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
    if window in {"7d", "30d"}:
        date -= dt.timedelta(days=int(window[:-1]) - 1)
    elif window == "month":
        date = date.replace(day=1)
    elif window != "today":
        raise ValueError("invalid window")
    return date.timestamp()


def window_bounds(window, timezone, now):
    """Closed calendar days use an exclusive end, in the site's timezone."""
    zone = ZoneInfo(timezone)
    today = dt.datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    if window == 'yesterday':
        return (today - dt.timedelta(days=1)).timestamp(), today.timestamp()
    if window.startswith('date:'):
        date = dt.date.fromisoformat(window[5:])
        if window[5:] != date.isoformat() or not 0 <= (today.date() - date).days < 30:
            raise ValueError('date must be within the last 30 calendar days')
        start = dt.datetime.combine(date, dt.time(), zone)
        return start.timestamp(), min(now, (start + dt.timedelta(days=1)).timestamp())
    return window_start(window, timezone, now), now


def historical_window(window, timezone, now):
    return window == 'yesterday' or bool(window and window.startswith('date:') and window[5:] < day_key(now, timezone))


class Store:
    def __init__(self, path, max_bytes=1024 ** 3):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(site TEXT,id TEXT,ts REAL,kind TEXT,path TEXT,resource TEXT,result TEXT,operation TEXT,
            PRIMARY KEY(site,id));
          CREATE INDEX IF NOT EXISTS event_time ON events(ts);
          CREATE UNIQUE INDEX IF NOT EXISTS operation_result ON events(site,operation,kind)
            WHERE operation != '' AND kind='export_result';
          CREATE TABLE IF NOT EXISTS visitors(site TEXT,day TEXT,id TEXT,last REAL,PRIMARY KEY(site,day,id));
          CREATE TABLE IF NOT EXISTS visitor_days(site TEXT,day TEXT,count INTEGER,PRIMARY KEY(site,day));
          CREATE TABLE IF NOT EXISTS counts(site TEXT,day TEXT,kind TEXT,label TEXT,result TEXT,count INTEGER,
            PRIMARY KEY(site,day,kind,label,result));
          CREATE TABLE IF NOT EXISTS traffic(site TEXT,minute INTEGER,path TEXT,category TEXT,status INTEGER,requests INTEGER,bytes INTEGER,
            PRIMARY KEY(site,minute,path,category,status));
          CREATE TABLE IF NOT EXISTS loads(source TEXT,ts REAL,data TEXT,PRIMARY KEY(source,ts));
          CREATE TABLE IF NOT EXISTS load_rollups(source TEXT,bucket INTEGER,resolution INTEGER,data TEXT,
            PRIMARY KEY(source,bucket,resolution));
        """)
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def close(self):
        with self.lock:
            self.db.close()

    def size(self):
        return sum(p.stat().st_size for p in [self.path, Path(str(self.path) + '-wal')] if p.exists())

    def ensure_capacity(self):
        if self.size() >= self.max_bytes:
            raise OverflowError("statistics storage limit reached")

    def state(self, key, default=None, db=None):
        if db is None:
            with self.lock:
                return self.state(key, default, self.db)
        row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value, db=None):
        if db is None:
            with self.transaction() as db:
                return self.set_state(key, value, db)
        db.execute("INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def add_event(self, event, timezone, now=None):
        now = time.time() if now is None else now
        self.ensure_capacity()
        site, kind = event['site'], event['type']
        day = day_key(now, timezone)
        result, resource = event.get('result', ''), event.get('resource', '')
        with self.transaction() as db:
            row = db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?)", (
                site, event['id'], now, kind, event['path'], resource, result, event.get('operation', '')))
            if not row.rowcount:
                return False
            label = event['path'] if kind == 'page_view' else resource
            db.execute("""INSERT INTO counts VALUES(?,?,?,?,?,1) ON CONFLICT(site,day,kind,label,result)
                DO UPDATE SET count=count+1""", (site, day, kind, label, result))
            if kind == 'page_view':
                db.execute("""INSERT INTO counts VALUES(?,?,'referrer',?,'',1)
                    ON CONFLICT(site,day,kind,label,result) DO UPDATE SET count=count+1""",
                    (site, day, event.get('referrer', 'direct')))
            visitor = event.get('visitor')
            if visitor:
                inserted = db.execute("INSERT OR IGNORE INTO visitors VALUES(?,?,?,?)", (site, day, visitor, now)).rowcount
                db.execute("UPDATE visitors SET last=? WHERE site=? AND day=? AND id=?", (now, site, day, visitor))
                if inserted:
                    db.execute("INSERT INTO visitor_days VALUES(?,?,1) ON CONFLICT(site,day) DO UPDATE SET count=count+1", (site, day))
            self.set_state('event:' + site, {'lastEvent': now}, db)
        return True

    def summary(self, site, window, now=None):
        now = time.time() if now is None else now
        since, until = window_bounds(window, site.get('timezone', 'Asia/Shanghai'), now)
        historical = historical_window(window, site.get('timezone', 'Asia/Shanghai'), now)
        end = until if historical else now + 0.000001
        day = day_key(since, site.get('timezone', 'Asia/Shanghai'))
        today = day_key(end - 0.000001, site.get('timezone', 'Asia/Shanghai'))
        sid = site['id']
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT kind,label,result,SUM(count) count FROM counts WHERE site=? AND day>=? AND day<=? GROUP BY kind,label,result ORDER BY count DESC", (sid, day, today))]
            totals = {}
            for row in rows:
                key = row['kind'] + (':' + row['result'] if row['result'] else '')
                totals[key] = totals.get(key, 0) + row['count']
            visitors = self.db.execute("SELECT COALESCE(SUM(count),0) FROM visitor_days WHERE site=? AND day>=? AND day<=?", (sid, day, today)).fetchone()[0]
            active = self.db.execute("SELECT COUNT(*) FROM visitors WHERE site=? AND day=? AND last>=?", (sid, today, now - 300)).fetchone()[0]
            traffic = [dict(r) for r in self.db.execute("SELECT category,SUM(requests) requests,SUM(bytes) bytes,SUM(CASE WHEN status>=400 THEN requests ELSE 0 END) errors FROM traffic WHERE site=? AND minute>=? AND minute<? GROUP BY category ORDER BY bytes DESC", (sid, since, end))]
            timeline = [dict(r) for r in self.db.execute("SELECT day,SUM(CASE WHEN kind='page_view' THEN count ELSE 0 END) views,SUM(CASE WHEN kind='download_click' THEN count ELSE 0 END) downloads FROM counts WHERE site=? AND day>=? AND day<=? GROUP BY day ORDER BY day", (sid, day, today))]
            if day == today:
                timeline = [dict(r) for r in self.db.execute("SELECT CAST(ts/3600 AS INTEGER)*3600 ts,SUM(kind='page_view') views,SUM(kind='download_click') downloads FROM events WHERE site=? AND ts>=? AND ts<? GROUP BY 1 ORDER BY 1", (sid, since, end))]
                for point in timeline:
                    point['label'] = dt.datetime.fromtimestamp(point['ts'], ZoneInfo(site.get('timezone', 'Asia/Shanghai'))).strftime('%H:%M')
            log_state = self.state('log:' + sid, {})
            event_state = self.state('event:' + sid, {})
            started = self.state('started:' + sid)
        return {'site': sid, 'since': since, 'until': until, 'historical': historical, 'startedAt': started,
                'exportResultsEnabled': site.get('exportResultsEnabled', True),
                'coverage': 'partial' if started is None or started > since else 'collecting',
                'totals': totals, 'dailyVisitorsSum': visitors, 'activeVisitors5m': None if historical else active,
                'pages': [r for r in rows if r['kind'] == 'page_view'][:20],
                'resources': [r for r in rows if r['kind'] in {'download_click', 'export_result'}][:30],
                'referrers': [r for r in rows if r['kind'] == 'referrer'][:15],
                'timeline': timeline, 'traffic': traffic, 'log': log_state, 'events': event_state,
                'storage': {'bytes': self.size(), 'limit': self.max_bytes}}

    def add_load(self, source, sample):
        self.ensure_capacity()
        with self.transaction() as db:
            if not db.execute('INSERT OR IGNORE INTO loads VALUES(?,?,?)', (source, sample['ts'], json.dumps(sample))).rowcount:
                return
            duration = sample.get('elapsed') or 0
            for resolution in (60, 3600):
                bucket = int(sample['ts']) // resolution * resolution
                row = db.execute('SELECT data FROM load_rollups WHERE source=? AND bucket=? AND resolution=?', (source, bucket, resolution)).fetchone()
                data = json.loads(row[0]) if row else {'seconds': 0, 'rxBytes': 0, 'txBytes': 0, 'metrics': {}}
                data['seconds'] += duration
                for name in ('rxBytes', 'txBytes'):
                    data[name] += sample.get(name) or 0
                for name in ('active', 'reading', 'writing', 'waiting', 'rps', 'rxMbps', 'txMbps'):
                    value = sample.get(name)
                    if value is None or not math.isfinite(value):
                        continue
                    metric = data['metrics'].setdefault(name, {'sum': 0, 'seconds': 0, 'max': value, 'maxAt': sample['ts']})
                    metric['sum'] += value * duration
                    metric['seconds'] += duration
                    if value >= metric['max']:
                        metric.update(max=value, maxAt=sample['ts'])
                db.execute('INSERT INTO load_rollups VALUES(?,?,?,?) ON CONFLICT(source,bucket,resolution) DO UPDATE SET data=excluded.data', (source, bucket, resolution, json.dumps(data)))

    def loads(self, source, seconds=3600, now=None, window=None, timezone="Asia/Shanghai"):
        now = time.time() if now is None else now
        since, until = window_bounds(window, timezone, now) if window else (now - seconds, now)
        historical = historical_window(window, timezone, now)
        end = until if historical else now + 0.000001
        resolution = 60 if window or seconds > 3600 else 5
        with self.lock:
            if resolution == 5:
                rows = self.db.execute('SELECT data FROM loads WHERE source=? AND ts>=? AND ts<? ORDER BY ts', (source, since, end)).fetchall()
                points = [json.loads(r[0]) for r in rows]
            else:
                points = []
                for row in self.db.execute('SELECT bucket,data FROM load_rollups WHERE source=? AND resolution=60 AND bucket>=? AND bucket<? ORDER BY bucket', (source, since, end)):
                    data = json.loads(row['data'])
                    point = {'ts': row['bucket'], 'rxBytes': data['rxBytes'], 'txBytes': data['txBytes'], 'gap': data['seconds'] < 45}
                    point.update({k: v['sum']/v['seconds'] if v['seconds'] else None for k, v in data['metrics'].items()})
                    point['txPeakMbps'] = data['metrics'].get('txMbps', {}).get('max')
                    point['txPeakAt'] = data['metrics'].get('txMbps', {}).get('maxAt')
                    points.append(point)
            recent = self.db.execute('SELECT data FROM loads WHERE source=? ORDER BY ts DESC LIMIT 1', (source,)).fetchone()
            totals = {}
            for period in ('today', 'month'):
                period_start = window_start(period, timezone, now)
                aggregate = [json.loads(r[0]) for r in self.db.execute('SELECT data FROM load_rollups WHERE source=? AND resolution=3600 AND bucket>=? AND bucket<=?', (source,period_start,now))]
                network_seconds = sum(r['metrics'].get('txMbps', {}).get('seconds', 0) for r in aggregate)
                totals[period] = {'rxBytes': sum(r['rxBytes'] for r in aggregate) if network_seconds else None,
                                  'txBytes': sum(r['txBytes'] for r in aggregate) if network_seconds else None,
                                  'coveredSeconds': network_seconds, 'windowSeconds': now-period_start}
        return {'source': source, 'latest': json.loads(recent[0]) if recent else None,
                'points': points, 'since': since, 'until': until, 'historical': historical, 'totals': totals, 'resolution': resolution, 'scope': 'instance / interface'}

    def prune(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            db.execute('DELETE FROM events WHERE ts<?', (now - 30 * 86400,))
            db.execute('DELETE FROM visitors WHERE last<?', (now - 48 * 3600,))
            day = dt.datetime.fromtimestamp(now - 366 * 86400, UTC).strftime('%Y-%m-%d')
            for table in ('counts', 'visitor_days'):
                db.execute(f'DELETE FROM {table} WHERE day<?', (day,))
            db.execute('DELETE FROM traffic WHERE minute<?', (now - 366 * 86400,))
            db.execute('DELETE FROM loads WHERE ts<?', (now - 86400,))
            db.execute('DELETE FROM load_rollups WHERE bucket<? AND resolution=60', (now - 30 * 86400,))
            db.execute('DELETE FROM load_rollups WHERE bucket<? AND resolution=3600', (now - 365 * 86400,))
        with self.lock:
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
