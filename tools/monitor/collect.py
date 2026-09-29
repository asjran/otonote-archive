#!/usr/bin/env python3

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import shutil
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.6-3.10 server compatibility
    tomllib = None


SCHEMA_VERSION = 3
LATENCY_BOUNDS_MS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def latency_upper_bound(milliseconds: float) -> int:
    for bound in LATENCY_BOUNDS_MS:
        if milliseconds <= bound:
            return bound
    return -1


def classify(path: str, content_type: str = "", user_agent: str = "") -> str:
    lower = path.lower()
    suffix = Path(lower).suffix
    if user_agent.startswith(("OurNotesSyntheticLoad/", "OurNotesPerformanceBrowser/")):
        return "synthetic"
    if lower.startswith("/__health") or lower == "/.release.json":
        return "health"
    if suffix in {".moc3", ".model3.json", ".physics3.json", ".exp3.json"} or "/live2d/" in lower:
        return "live2d"
    if suffix in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}:
        return "audio"
    if suffix in {".mp4", ".webm", ".mov"}:
        return "video"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg"}:
        return "image"
    if suffix in {".js", ".css", ".woff", ".woff2", ".ttf"}:
        return "static"
    if suffix == ".json" or "application/json" in content_type:
        return "data"
    if suffix in {".apk", ".zip", ".7z", ".tar", ".gz"}:
        return "download"
    if not suffix or suffix in {".html", ".htm"} or "text/html" in content_type:
        return "page"
    return "unknown"


def classify_outcome(
    status: int,
    category: str,
    limit_conn_status: str = "",
    limit_req_status: str = "",
) -> str:
    if category == "synthetic":
        return "synthetic"
    if category == "health":
        return "health"
    rejected = "REJECTED" in {
        str(limit_conn_status or "").upper(),
        str(limit_req_status or "").upper(),
    }
    if status == 503 and rejected:
        return "capacity_rejection"
    if 200 <= status < 400:
        return "success"
    if 400 <= status < 500:
        return "client_error"
    if status in {500, 502, 503, 504}:
        return "server_error"
    return "server_error_unclassified"


def bucket_time(raw: str) -> str:
    try:
        parsed = dt.datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        offset = raw[19:]
        if offset == "Z" or not offset:
            timezone = dt.timezone.utc
        else:
            sign = 1 if offset.startswith("+") else -1
            hours, minutes = offset[1:].split(":", 1)
            timezone = dt.timezone(sign * dt.timedelta(hours=int(hours), minutes=int(minutes)))
        parsed = parsed.replace(tzinfo=timezone)
    except (ValueError, TypeError):
        parsed = dt.datetime.now(dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS minute_metrics (
          bucket TEXT NOT NULL,
          category TEXT NOT NULL,
          status INTEGER NOT NULL,
          protocol TEXT NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          bytes INTEGER NOT NULL DEFAULT 0,
          total_ms REAL NOT NULL DEFAULT 0,
          range_requests INTEGER NOT NULL DEFAULT 0,
          not_modified INTEGER NOT NULL DEFAULT 0,
          errors INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (bucket, category, status, protocol)
        );
        CREATE TABLE IF NOT EXISTS daily_paths (
          day TEXT NOT NULL,
          path TEXT NOT NULL,
          category TEXT NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          bytes INTEGER NOT NULL DEFAULT 0,
          total_ms REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (day, path, category)
        );
        CREATE TABLE IF NOT EXISTS daily_visitors (
          day TEXT NOT NULL,
          visitor_hash TEXT NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (day, visitor_hash)
        );
        CREATE TABLE IF NOT EXISTS latency_histogram (
          bucket TEXT NOT NULL,
          category TEXT NOT NULL,
          upper_ms INTEGER NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (bucket, category, upper_ms)
        );
        CREATE TABLE IF NOT EXISTS outcome_metrics (
          bucket TEXT NOT NULL,
          outcome TEXT NOT NULL,
          status INTEGER NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          bytes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (bucket, outcome, status)
        );
        """
    )
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
    return db


def database_is_healthy(path: Path) -> bool:
    if not path.is_file():
        return True
    try:
        db = sqlite3.connect(str(path))
        result = db.execute("PRAGMA integrity_check").fetchone()
        db.close()
        return bool(result and result[0] == "ok")
    except sqlite3.DatabaseError:
        return False


def recover_database(path: Path, backup_path: Path) -> bool:
    if database_is_healthy(path):
        return False
    if not backup_path.is_file() or not database_is_healthy(backup_path):
        raise sqlite3.DatabaseError("monitor database corrupt and backup unavailable")
    temporary = path.with_name(path.name + ".recovering")
    shutil.copy2(backup_path, temporary)
    temporary.replace(path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    return True


def backup_database(db: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup_path.with_name(backup_path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    backup = getattr(db, "backup", None)
    if callable(backup):
        destination = sqlite3.connect(str(temporary))
        try:
            backup(destination)
        finally:
            destination.close()
    else:
        # Python 3.6's sqlite3 module does not expose Connection.backup().
        # The monitor is the only writer, so a completed WAL checkpoint gives
        # us a consistent main database file that can be copied atomically.
        db.commit()
        source_row = next(
            (row for row in db.execute("PRAGMA database_list") if row[1] == "main"),
            None,
        )
        if source_row is None or not source_row[2]:
            raise sqlite3.DatabaseError("monitor database path is unavailable")
        checkpoint = db.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
        if checkpoint and checkpoint[0] != 0:
            raise sqlite3.DatabaseError("monitor database WAL checkpoint is busy")
        shutil.copy2(Path(source_row[2]), temporary)
    if not database_is_healthy(temporary):
        temporary.unlink()
        raise sqlite3.DatabaseError("monitor database backup failed integrity check")
    temporary.replace(backup_path)


def load_config(path: Path) -> dict:
    if tomllib is not None:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    result = {}
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result.setdefault(section, {})
            continue
        key, separator, value = line.partition("=")
        if not separator or not section:
            raise ValueError(f"unsupported config line: {raw}")
        result[section][key.strip()] = value.strip().strip('"')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Incrementally aggregate OurNotes JSON access logs")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_config(Path(args.config))
    log_path = Path(config["paths"]["access_log"])
    db_path = Path(config["paths"]["database"])
    backup_path = Path(
        config["paths"].get("backup", str(db_path) + ".backup")
    )
    if not log_path.exists():
        print(json.dumps({"status": "no-log", "path": str(log_path)}))
        return 0
    recovered = recover_database(db_path, backup_path)
    db = connect(db_path)
    stat = log_path.stat()
    inode = str(stat.st_ino)
    old_inode_row = db.execute("SELECT value FROM meta WHERE key='access_inode'").fetchone()
    offset_row = db.execute("SELECT value FROM meta WHERE key='access_offset'").fetchone()
    offset = int(offset_row[0]) if offset_row and old_inode_row and old_inode_row[0] == inode else 0
    if offset > stat.st_size:
        offset = 0
    processed = invalid = 0
    started = time.monotonic()
    with log_path.open("r", encoding="utf-8", errors="replace") as handle, db:
        handle.seek(offset)
        for line in handle:
            try:
                item = json.loads(line)
                path = str(item.get("path") or "/").split("?", 1)[0]
                status = int(item.get("status") or 0)
                sent = int(item.get("bytes") or 0)
                request_ms = float(item.get("request_time") or 0) * 1000
                protocol = str(item.get("protocol") or "unknown")
                bucket = bucket_time(str(item.get("time") or ""))
                day = bucket[:10]
                category = classify(
                    path,
                    str(item.get("content_type") or ""),
                    str(item.get("user_agent") or ""),
                )
                outcome = classify_outcome(
                    status,
                    category,
                    str(item.get("limit_conn_status") or ""),
                    str(item.get("limit_req_status") or ""),
                )
                is_range = 1 if item.get("range") not in {None, "", "-"} else 0
                is_error = 1 if status >= 400 or status == 0 else 0
                db.execute(
                    """INSERT INTO outcome_metrics(bucket, outcome, status, requests, bytes)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(bucket, outcome, status) DO UPDATE SET
                    requests=requests+1, bytes=bytes+excluded.bytes""",
                    (bucket, outcome, status, sent),
                )
                db.execute(
                    """INSERT INTO minute_metrics
                    (bucket, category, status, protocol, requests, bytes, total_ms, range_requests, not_modified, errors)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(bucket, category, status, protocol) DO UPDATE SET
                    requests=requests+1, bytes=bytes+excluded.bytes, total_ms=total_ms+excluded.total_ms,
                    range_requests=range_requests+excluded.range_requests,
                    not_modified=not_modified+excluded.not_modified, errors=errors+excluded.errors""",
                    (bucket, category, status, protocol, sent, request_ms, is_range, 1 if status == 304 else 0, is_error),
                )
                db.execute(
                    """INSERT INTO latency_histogram
                    (bucket, category, upper_ms, requests)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(bucket, category, upper_ms) DO UPDATE SET
                    requests=requests+1""",
                    (bucket, category, latency_upper_bound(request_ms)),
                )
                db.execute(
                    """INSERT INTO daily_paths(day, path, category, requests, bytes, total_ms)
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(day, path, category) DO UPDATE SET
                    requests=requests+1, bytes=bytes+excluded.bytes, total_ms=total_ms+excluded.total_ms""",
                    (day, path[:512], category, sent, request_ms),
                )
                if category not in {"synthetic", "health"}:
                    remote = str(item.get("remote") or "unknown")
                    salt = str(config.get("privacy", {}).get("daily_salt", "ournotes-change-me"))
                    visitor = hashlib.sha256(f"{day}:{salt}:{remote}".encode()).hexdigest()[:24]
                    db.execute(
                        """INSERT INTO daily_visitors(day, visitor_hash, requests) VALUES(?, ?, 1)
                        ON CONFLICT(day, visitor_hash) DO UPDATE SET requests=requests+1""",
                        (day, visitor),
                    )
                processed += 1
            except (ValueError, TypeError, json.JSONDecodeError):
                invalid += 1
        new_offset = handle.tell()
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('access_inode', ?)", (inode,))
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('access_offset', ?)", (str(new_offset),))
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_success', ?)", (dt.datetime.now(dt.timezone.utc).isoformat(),))
        invalid_row = db.execute("SELECT value FROM meta WHERE key='invalid_lines'").fetchone()
        invalid_total = (int(invalid_row[0]) if invalid_row else 0) + invalid
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('invalid_lines', ?)", (str(invalid_total),))
        minute_cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).replace(
            second=0, microsecond=0
        ).isoformat().replace("+00:00", "Z")
        db.execute("DELETE FROM minute_metrics WHERE bucket < ?", (minute_cutoff,))
        db.execute("DELETE FROM latency_histogram WHERE bucket < ?", (minute_cutoff,))
        db.execute("DELETE FROM outcome_metrics WHERE bucket < ?", (minute_cutoff,))
        db.execute("DELETE FROM daily_paths WHERE day < date('now', '-730 days')")
        db.execute("DELETE FROM daily_visitors WHERE day < date('now', '-730 days')")
    backup_database(db, backup_path)
    db.close()
    print(json.dumps({"processed": processed, "invalid": invalid, "recovered": recovered, "elapsedMs": round((time.monotonic() - started) * 1000, 2)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
