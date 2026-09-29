"""Small durable outbox; use a single application process/consumer."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path


class Outbox:
    def __init__(self, path: Path, limit: int = 200):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, payload TEXT NOT NULL, sender TEXT NOT NULL,
            created REAL NOT NULL, expires REAL NOT NULL, next_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '')""")
        self.db.commit()
        self.limit = limit

    def enqueue(self, payload: dict, now: float | None = None) -> str:
        now = time.time() if now is None else now
        key = hashlib.sha256(json.dumps([payload["scene"], payload["target"], payload["message_id"]]).encode()).hexdigest()
        sender = hashlib.sha256((payload["scene"] + ":" + payload["target"] + ":" + payload["sender"]).encode()).hexdigest()
        with self.db:
            self.db.execute("DELETE FROM jobs WHERE created < ? AND state != 'pending'", (now - 86400,))
            if self.db.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone():
                return "duplicate"
            if self.db.execute("SELECT count(*) FROM jobs WHERE state='pending'").fetchone()[0] >= self.limit:
                return "full"
            if self.db.execute("SELECT count(*) FROM jobs WHERE sender=? AND created>?", (sender, now - 60)).fetchone()[0] >= 10:
                return "rate_limited"
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                return "full"
            self.db.execute("INSERT INTO jobs(key,payload,sender,created,expires,next_at) VALUES(?,?,?,?,?,?)",
                            (key, json.dumps(payload, ensure_ascii=False), sender, now, payload["expires"], now))
        return "accepted"

    def next(self, now: float | None = None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("UPDATE jobs SET state='failed',error='reply_expired' WHERE state='pending' AND expires<=?", (now,))
        row = self.db.execute("SELECT * FROM jobs WHERE state='pending' AND next_at<=? ORDER BY created LIMIT 1", (now,)).fetchone()
        return dict(row) if row else None

    def sent(self, key: str, count: int):
        with self.db:
            self.db.execute("UPDATE jobs SET sent=? WHERE key=?", (count, key))

    def finish(self, key: str):
        with self.db:
            self.db.execute("UPDATE jobs SET state='sent', payload='{}' WHERE key=?", (key,))

    def fail(self, job: dict, code: str, retryable: bool, delay: float):
        attempts = job["attempts"] + 1
        retry = retryable and attempts < 3 and time.time() + delay < job["expires"]
        with self.db:
            self.db.execute("UPDATE jobs SET state=?,error=?,attempts=?,next_at=? WHERE key=?",
                            ("pending" if retry else "failed", code, attempts, time.time() + delay, job["key"]))

    def counts(self) -> dict:
        return {row[0]: row[1] for row in self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")}

    def close(self):
        self.db.close()


class Images:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        name = hashlib.sha256(data).hexdigest() + ".png"
        path = self.root / name
        if not path.exists():
            temporary = self.root / (name + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        path.touch()
        return name

    def sweep(self):
        files = sorted(self.root.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
        total = 0
        for index, path in enumerate(files):
            stat = path.stat()
            total += stat.st_size
            if index >= 1000 or total > 512 * 1024 * 1024 or stat.st_mtime < time.time() - 86400:
                path.unlink(missing_ok=True)
