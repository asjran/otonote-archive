#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import socket
import ssl
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def load_config(path):
    if tomllib is not None:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    result = {}
    section = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            result.setdefault(section, {})
            continue
        key, separator, value = line.partition("=")
        if not separator or not section:
            raise ValueError("unsupported config line: {}".format(raw))
        raw_value = value.strip()
        if raw_value.startswith('"') and raw_value.endswith('"'):
            parsed = raw_value[1:-1]
        else:
            try:
                parsed = int(raw_value)
            except ValueError:
                parsed = raw_value
        result[section][key.strip()] = parsed
    return result


class HttpProbeClient:
    def check(self, url, *, timeout, range_header=None):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("probe URL must be http or https")
        started = time.monotonic()
        dns_started = time.monotonic()
        socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        dns_ms = (time.monotonic() - dns_started) * 1000
        connection_started = time.monotonic()
        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_class(parsed.hostname, parsed.port, timeout=timeout)
        headers = {"User-Agent": "OurNotesBlackboxProbe/1.0"}
        if range_header:
            headers["Range"] = range_header
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        ttfb_ms = (time.monotonic() - started) * 1000
        response.read(1)
        certificate_days = None
        if parsed.scheme == "https" and getattr(connection, "sock", None):
            certificate = connection.sock.getpeercert()
            if certificate.get("notAfter"):
                expires = dt.datetime.fromtimestamp(
                    ssl.cert_time_to_seconds(certificate["notAfter"]), dt.timezone.utc
                )
                certificate_days = (expires - dt.datetime.now(dt.timezone.utc)).days
        result = {
            "dnsMs": round(dns_ms, 2),
            "tcpMs": None,
            "tlsMs": round((time.monotonic() - connection_started) * 1000, 2) if parsed.scheme == "https" else None,
            "status": response.status,
            "ttfbMs": round(ttfb_ms, 2),
            "totalMs": round((time.monotonic() - started) * 1000, 2),
            "certificateDaysRemaining": certificate_days,
            "acceptRanges": response.getheader("Accept-Ranges") == "bytes",
            "contentRange": response.getheader("Content-Range"),
        }
        connection.close()
        return result


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_probe(config, client=None, now=None):
    target = str(config.get("target", {}).get("base_url") or "").rstrip("/")
    if not target:
        raise ValueError("target.base_url is required")
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target.base_url must be an absolute http(s) URL")
    paths = config.get("paths", {})
    required = ("homepage", "representative", "static", "media")
    if any(not paths.get(key) for key in required):
        raise ValueError("paths must define homepage, representative, static and media")
    thresholds = config.get("thresholds", {})
    timeout = float(thresholds.get("timeout_seconds", 10))
    cert_attention = int(thresholds.get("certificate_attention_days", 30))
    cert_incident = int(thresholds.get("certificate_incident_days", 7))
    client = client or HttpProbeClient()
    now = now or dt.datetime.now(dt.timezone.utc)
    checks = {}
    alerts = []
    for name in required:
        range_header = "bytes=0-0" if name == "media" else None
        try:
            result = client.check(urljoin(target + "/", str(paths[name]).lstrip("/")), timeout=timeout, range_header=range_header)
            expected = 206 if name == "media" else 200
            valid_range = bool(result.get("contentRange")) and result.get("status") == 206
            result["range"] = {"requested": bool(range_header), "valid": valid_range if range_header else None}
            if result.get("status") != expected or (range_header and not valid_range):
                alerts.append({"code": "http_contract_failed", "severity": "incident", "check": name})
            days = result.get("certificateDaysRemaining")
            if days is not None and days <= cert_incident:
                alerts.append({"code": "certificate_expiring", "severity": "incident", "days": days})
            elif days is not None and days <= cert_attention:
                alerts.append({"code": "certificate_expiring", "severity": "attention", "days": days})
            checks[name] = result
        except Exception as exc:
            checks[name] = {"error": type(exc).__name__}
            alerts.append({"code": "probe_request_failed", "severity": "incident", "check": name})
    severity = "incident" if any(item["severity"] == "incident" for item in alerts) else (
        "attention" if alerts else "normal"
    )
    report = {
        "schemaVersion": 1,
        "target": target,
        "checkedAt": now.isoformat().replace("+00:00", "Z"),
        "severity": severity,
        "failureCode": alerts[0]["code"] if alerts else None,
        "checks": checks,
        "alerts": alerts,
    }
    output = config.get("output", {}).get("alerts")
    if output:
        _atomic_json(output, report)
    return report


def exit_code_for(report):
    return {"normal": 0, "attention": 1, "incident": 2, "invalid_configuration": 3}.get(
        report.get("severity"), 2
    )


def main():
    parser = argparse.ArgumentParser(description="Run the OurNotes external blackbox probe")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        report = run_probe(load_config(args.config))
    except (OSError, ValueError) as exc:
        print(json.dumps({"schemaVersion": 1, "severity": "invalid_configuration", "failureCode": "invalid_configuration", "detail": str(exc)}))
        return 3
    print(json.dumps(report, ensure_ascii=False))
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
