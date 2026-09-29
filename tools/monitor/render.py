#!/usr/bin/env python3

import argparse
import csv
import datetime as dt
import html
import json
import os
import sqlite3
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.6-3.10 server compatibility
    tomllib = None


CST = dt.timezone(dt.timedelta(hours=8))
CATEGORY_LABELS = {
    "page": "网页",
    "data": "页面数据",
    "static": "样式、脚本和字体",
    "image": "图片",
    "live2d": "Live2D",
    "audio": "音频",
    "video": "视频",
    "download": "原始下载",
    "health": "健康检查",
    "synthetic": "性能测试",
    "unknown": "其他资源",
}
ROUTE_LABELS = {
    "/": "站点入口",
    "/global/zh-CN": "中文站首页",
    "/global/en": "英文站首页",
    "/global/zh-CN/tools": "工具首页",
    "/global/zh-CN/characters": "角色资料库",
    "/global/zh-CN/music": "音乐资料库",
    "/global/zh-CN/cards": "卡牌资料库",
    "/global/zh-CN/database": "游戏数据库",
    "/global/zh-CN/stories": "剧情档案",
    "/global/zh-CN/resources/media/device": "设备媒体档案",
}
WINDOWS = (
    ("5m", dt.timedelta(minutes=5), "5 分钟"),
    ("1h", dt.timedelta(hours=1), "1 小时"),
    ("24h", dt.timedelta(hours=24), "24 小时"),
    ("7d", dt.timedelta(days=7), "7 天"),
)
LARGE_MEDIA_CATEGORIES = {"live2d", "audio", "video", "download"}
THRESHOLDS = {
    "serverError5mMinimum": 3,
    "serverError5mRate": 0.01,
    "serverError1hMinimum": 10,
    "bandwidthAttentionMbps": 2.4,
    "freshnessAttentionMinutes": 10,
    "freshnessIncidentMinutes": 20,
}


def calculate_monitor_freshness_minutes(raw_timestamp, now):
    if not isinstance(raw_timestamp, str):
        raise TypeError("monitor timestamp must be a string")
    timestamp = raw_timestamp.strip()
    if timestamp.endswith("Z"):
        body = timestamp[:-1]
        offset = dt.timedelta(0)
    elif len(timestamp) >= 6 and timestamp[-6] in "+-" and timestamp[-3] == ":":
        offset_text = timestamp[-6:]
        body = timestamp[:-6]
        offset = dt.timedelta(
            hours=int(offset_text[1:3]),
            minutes=int(offset_text[4:6]),
        )
        if offset_text[0] == "-":
            offset = -offset
    else:
        raise ValueError("monitor timestamp must include a timezone")
    timestamp_format = "%Y-%m-%dT%H:%M:%S.%f" if "." in body else "%Y-%m-%dT%H:%M:%S"
    heartbeat = dt.datetime.strptime(body, timestamp_format).replace(tzinfo=dt.timezone(offset))
    return max(0, round((now - heartbeat).total_seconds() / 60, 2))


def evaluate_monitor_status(windows, peak_mbps, freshness_minutes, page_views):
    alerts = []
    five = windows.get("5m", {})
    hour = windows.get("1h", {})
    five_outcomes = five.get("outcomes", {})
    hour_outcomes = hour.get("outcomes", {})
    five_server = int(five_outcomes.get("server_error", 0)) + int(
        five_outcomes.get("server_error_unclassified", 0)
    )
    hour_server = int(hour_outcomes.get("server_error", 0)) + int(
        hour_outcomes.get("server_error_unclassified", 0)
    )
    five_rate = five_server / max(1, int(five.get("requests", 0)))
    if (
        five_server >= THRESHOLDS["serverError5mMinimum"]
        and five_rate >= THRESHOLDS["serverError5mRate"]
    ):
        alerts.append({"code": "origin_error_rate_5m", "severity": "incident", "count": five_server})
    elif hour_server >= THRESHOLDS["serverError1hMinimum"]:
        alerts.append({"code": "origin_errors_1h", "severity": "incident", "count": hour_server})
    elif hour_server:
        alerts.append({"code": "origin_errors_observed", "severity": "attention", "count": hour_server})
    capacity = int(five_outcomes.get("capacity_rejection", 0))
    if capacity:
        alerts.append({"code": "capacity_rejection", "severity": "attention", "count": capacity})
    if peak_mbps >= THRESHOLDS["bandwidthAttentionMbps"]:
        alerts.append({"code": "bandwidth_near_limit", "severity": "attention", "value": peak_mbps})
    if freshness_minutes > THRESHOLDS["freshnessIncidentMinutes"]:
        alerts.append({"code": "monitor_data_stale", "severity": "incident", "minutes": freshness_minutes})
    elif freshness_minutes > THRESHOLDS["freshnessAttentionMinutes"]:
        alerts.append({"code": "monitor_data_delayed", "severity": "attention", "minutes": freshness_minutes})
    code = "incident" if any(item["severity"] == "incident" for item in alerts) else (
        "attention" if alerts else ("quiet" if page_views == 0 else "normal")
    )
    return {"code": code, "alerts": alerts}


def load_config(path):
    if tomllib is not None:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    result = {}
    section = ""
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result.setdefault(section, {})
            continue
        key, separator, value = line.partition("=")
        if not separator or not section:
            raise ValueError("unsupported config line: {}".format(raw))
        result[section][key.strip()] = value.strip().strip('"')
    return result


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def human_bytes(value):
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return "{} {}".format(int(size), unit)
            return "{:.1f} {}".format(size, unit)
        size /= 1024


def human_duration(value):
    milliseconds = float(value or 0)
    if milliseconds <= 0:
        return "不足 1 毫秒"
    if milliseconds < 1000:
        return "{:.0f} 毫秒".format(milliseconds)
    return "{:.1f} 秒".format(milliseconds / 1000)


def normalized_route(path):
    value = path or "/"
    if value.endswith("/index.html"):
        value = value[:-11]
    elif value == "/index.html":
        value = "/"
    return value.rstrip("/") or "/"


def route_label(path):
    route = normalized_route(path)
    if route in ROUTE_LABELS:
        return ROUTE_LABELS[route]
    parts = [part for part in route.split("/") if part]
    if "music" in parts and len(parts) > parts.index("music") + 1:
        return "歌曲详情 · {}".format(parts[-1])
    if "characters" in parts and len(parts) > parts.index("characters") + 1:
        return "角色详情 · {}".format(parts[-1])
    if "stories" in parts and "episodes" in parts:
        return "剧情正文 · {}".format(parts[-1])
    if route.startswith("/media/") or "/media/" in route:
        return "{} · {}".format(CATEGORY_LABELS.get("unknown"), parts[-1] if parts else route)
    return route


def category_record(row):
    return {
        "category": row[0],
        "label": CATEGORY_LABELS.get(row[0], row[0]),
        "requests": int(row[1] or 0),
        "bytes": int(row[2] or 0),
        "averageMs": round(float(row[3] or 0) / row[1], 2) if row[1] else 0,
        "errors": int(row[4] or 0),
        "rangeRequests": int(row[5] or 0),
        "notModified": int(row[6] or 0),
    }


def path_record(row):
    return {
        "path": row[0],
        "label": route_label(row[0]),
        "category": row[1],
        "categoryLabel": CATEGORY_LABELS.get(row[1], row[1]),
        "requests": int(row[2] or 0),
        "bytes": int(row[3] or 0),
        "averageMs": round(float(row[4] or 0) / row[2], 2) if row[2] else 0,
    }


def traffic_class(category):
    if category == "synthetic":
        return "synthetic"
    if category == "health":
        return "health"
    if category in LARGE_MEDIA_CATEGORIES:
        return "largeMedia"
    return "normal"


def approximate_percentiles(histogram):
    total = sum(histogram.values())
    if not total:
        return {"p50": 0, "p95": 0, "p99": 0}
    result = {}
    for label, percentile in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99)):
        target = max(1, int(total * percentile + 0.999999))
        running = 0
        value = 0
        for upper, count in sorted(
            histogram.items(), key=lambda item: 1000000000 if item[0] == -1 else item[0]
        ):
            running += count
            if running >= target:
                value = 10000 if upper == -1 else upper
                break
        result[label] = value
    return result


def build_window_summary(db, now, delta):
    since = (now - delta).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    traffic = {
        key: {"requests": 0, "bytes": 0, "errors": 0, "latencyMs": {"p50": 0, "p95": 0, "p99": 0}}
        for key in ("normal", "synthetic", "health", "largeMedia")
    }
    for category, requests, sent, errors in db.execute(
        """SELECT category, SUM(requests), SUM(bytes), SUM(errors)
        FROM minute_metrics WHERE bucket >= ? GROUP BY category""",
        (since,),
    ):
        item = traffic[traffic_class(category)]
        item["requests"] += int(requests or 0)
        item["bytes"] += int(sent or 0)
        item["errors"] += int(errors or 0)
    histograms = {key: {} for key in traffic}
    for category, upper, requests in db.execute(
        """SELECT category, upper_ms, SUM(requests)
        FROM latency_histogram WHERE bucket >= ?
        GROUP BY category, upper_ms""",
        (since,),
    ):
        target = histograms[traffic_class(category)]
        target[int(upper)] = target.get(int(upper), 0) + int(requests or 0)
    for key in traffic:
        traffic[key]["latencyMs"] = approximate_percentiles(histograms[key])
    combined = {}
    for histogram in histograms.values():
        for upper, requests in histogram.items():
            combined[upper] = combined.get(upper, 0) + requests
    outcomes = {
        str(row[0]): int(row[1] or 0)
        for row in db.execute(
            "SELECT outcome, SUM(requests) FROM outcome_metrics WHERE bucket >= ? GROUP BY outcome",
            (since,),
        )
    }
    return {
        "requests": sum(item["requests"] for item in traffic.values()),
        "bytes": sum(item["bytes"] for item in traffic.values()),
        "errors": sum(item["errors"] for item in traffic.values()),
        "latencyMs": approximate_percentiles(combined),
        "traffic": traffic,
        "outcomes": outcomes,
    }


def load_deployment_events(path):
    if not path or not Path(path).is_file():
        return {"events": [], "attempts": [], "invalidLines": 0}
    events = []
    invalid = 0
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                events.append(value)
            else:
                invalid += 1
        except (ValueError, TypeError):
            invalid += 1
    recent = events[-100:]
    grouped = {}
    order = []
    for event in recent:
        attempt_id = str(event.get("attemptId") or event.get("releaseId") or "legacy")
        if attempt_id not in grouped:
            grouped[attempt_id] = {
                "attemptId": attempt_id,
                "command": event.get("command", "deploy"),
                "releaseId": event.get("releaseId"),
                "gitCommit": event.get("gitCommit"),
                "startedAt": event.get("startedAt"),
                "finishedAt": event.get("finishedAt"),
                "results": [],
                "failedPhase": None,
                "reasonCode": None,
            }
            order.append(attempt_id)
        attempt = grouped[attempt_id]
        result = event.get("result", "success" if "phases" in event else "unknown")
        attempt["results"].append(result)
        attempt["finishedAt"] = event.get("finishedAt") or attempt["finishedAt"]
        attempt["failedPhase"] = event.get("failedPhase") or attempt["failedPhase"]
        attempt["reasonCode"] = event.get("reasonCode") or attempt["reasonCode"]
    return {
        "events": recent[-20:],
        "attempts": [grouped[key] for key in order[-20:]],
        "invalidLines": invalid,
    }


def main():
    parser = argparse.ArgumentParser(description="Render static OurNotes traffic reports")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    db = sqlite3.connect(config["paths"]["database"])
    report_dir = Path(config["paths"]["report_dir"])
    now = dt.datetime.now(dt.timezone.utc)
    deployment_events = load_deployment_events(
        config.get("paths", {}).get("deployment_log")
    )
    since_time = (now - dt.timedelta(hours=24)).replace(second=0, microsecond=0)
    since = since_time.isoformat().replace("+00:00", "Z")
    since_day = since_time.date().isoformat()

    rows = db.execute(
        """SELECT category, SUM(requests), SUM(bytes), SUM(total_ms), SUM(errors),
        SUM(range_requests), SUM(not_modified)
        FROM minute_metrics WHERE bucket >= ? GROUP BY category ORDER BY SUM(bytes) DESC""",
        (since,),
    ).fetchall()
    category_map = {row[0]: category_record(row) for row in rows}
    categories = [category_map[key] for key in category_map if key not in {"synthetic", "health"}]
    categories.sort(key=lambda item: item["bytes"], reverse=True)
    synthetic = category_map.get("synthetic", {
        "category": "synthetic", "label": "性能测试", "requests": 0, "bytes": 0,
        "averageMs": 0, "errors": 0, "rangeRequests": 0, "notModified": 0,
    })
    health = category_map.get("health", {"requests": 0, "bytes": 0, "errors": 0})

    totals = {
        "requests": sum(item["requests"] for item in category_map.values()),
        "bytes": sum(item["bytes"] for item in category_map.values()),
        "errors": sum(item["errors"] for item in category_map.values()),
        "rangeRequests": sum(item.get("rangeRequests", 0) for item in category_map.values()),
        "notModified": sum(item.get("notModified", 0) for item in category_map.values()),
    }
    real = {
        "requests": sum(item["requests"] for item in categories),
        "pageViews": category_map.get("page", {}).get("requests", 0),
        "bytes": sum(item["bytes"] for item in categories),
        "errors": sum(item["errors"] for item in categories),
        "rangeRequests": sum(item.get("rangeRequests", 0) for item in categories),
        "notModified": sum(item.get("notModified", 0) for item in categories),
        "visitors": db.execute(
            "SELECT COUNT(*) FROM daily_visitors WHERE day >= ?", (since_day,)
        ).fetchone()[0],
    }
    peak_bytes = db.execute(
        """SELECT COALESCE(MAX(total_bytes), 0) FROM (
          SELECT bucket, SUM(bytes) AS total_bytes FROM minute_metrics
          WHERE bucket >= ? AND category NOT IN ('synthetic', 'health') GROUP BY bucket
        )""",
        (since,),
    ).fetchone()[0]
    real["peakMbps"] = round(float(peak_bytes or 0) * 8 / 60 / 1000000, 3)
    real["bandwidthPercent"] = round(min(100, real["peakMbps"] / 3 * 100), 1)

    hour_floor = now.replace(minute=0, second=0, microsecond=0)
    hour_rows = db.execute(
        """SELECT substr(bucket, 1, 13) AS hour_key,
        SUM(CASE WHEN category NOT IN ('synthetic', 'health') THEN requests ELSE 0 END),
        SUM(CASE WHEN category = 'synthetic' THEN requests ELSE 0 END)
        FROM minute_metrics WHERE bucket >= ? GROUP BY hour_key""",
        (since,),
    ).fetchall()
    hourly_map = {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in hour_rows}
    timeline = []
    for offset in range(23, -1, -1):
        point = hour_floor - dt.timedelta(hours=offset)
        key = point.strftime("%Y-%m-%dT%H")
        real_count, test_count = hourly_map.get(key, (0, 0))
        timeline.append({
            "hour": point.astimezone(CST).strftime("%H:00"),
            "realRequests": real_count,
            "syntheticRequests": test_count,
        })

    path_rows = db.execute(
        """SELECT path, category, SUM(requests), SUM(bytes), SUM(total_ms)
        FROM daily_paths WHERE day >= ? AND category NOT IN ('synthetic', 'health')
        GROUP BY path, category ORDER BY SUM(bytes) DESC LIMIT 50""",
        (since_day,),
    ).fetchall()
    top_paths = [path_record(row) for row in path_rows]
    popular_pages = sorted(
        [item for item in top_paths if item["category"] == "page"],
        key=lambda item: (item["requests"], item["bytes"]), reverse=True,
    )[:6]
    slow_paths = sorted(
        [item for item in top_paths if item["averageMs"] > 0],
        key=lambda item: item["averageMs"], reverse=True,
    )[:6]
    meta = dict(db.execute("SELECT key, value FROM meta"))
    generated_at_cst = now.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    windows = {
        key: {"label": label, **build_window_summary(db, now, delta)}
        for key, delta, label in WINDOWS
    }
    real["serverErrors"] = int(windows["24h"]["outcomes"].get("server_error", 0)) + int(
        windows["24h"]["outcomes"].get("server_error_unclassified", 0)
    )
    heartbeat_raw = meta.get("last_success")
    try:
        freshness_minutes = calculate_monitor_freshness_minutes(heartbeat_raw, now)
    except (TypeError, ValueError):
        freshness_minutes = 1000000
    last_log_row = db.execute("SELECT MAX(bucket) FROM minute_metrics").fetchone()
    evaluation = evaluate_monitor_status(windows, real["peakMbps"], freshness_minutes, real["pageViews"])
    status = evaluation["code"]
    if status == "incident":
        status_label = "存在需要处理的故障"
        conclusion = "监控发现持续源站错误或数据已明显陈旧，请按告警代码排查。"
    elif status == "attention":
        status_label = "需要留意"
        conclusion = "监控发现未达到事故门槛的源站错误、容量拒绝、出口压力或数据延迟。"
    elif status == "quiet":
        status_label = "运行正常，暂无真实页面访问"
        conclusion = "采集心跳正常；当前没有可识别的真实页面访问。"
    else:
        status_label = "运行正常"
        conclusion = "源站错误、容量拒绝、出口与采集新鲜度均未越过门槛。"
    summary = {
        "generatedAt": now.isoformat(),
        "generatedAtCst": generated_at_cst,
        "window": "24h",
        "status": {"code": status, "label": status_label, "conclusion": conclusion},
        "alerts": evaluation["alerts"],
        "thresholds": THRESHOLDS,
        "outcomes": windows["24h"]["outcomes"],
        "freshness": {
            "heartbeatAt": heartbeat_raw,
            "lastLogAt": last_log_row[0] if last_log_row else None,
            "lagMinutes": freshness_minutes,
            "targetMinutes": THRESHOLDS["freshnessAttentionMinutes"],
            "incidentMinutes": THRESHOLDS["freshnessIncidentMinutes"],
        },
        "totals": totals,
        "real": real,
        "synthetic": synthetic,
        "health": health,
        "categories": categories,
        "timeline": timeline,
        "popularPages": popular_pages,
        "topPaths": top_paths,
        "slowPaths": slow_paths,
        "meta": meta,
        "windows": windows,
        "deploymentEvents": deployment_events,
    }
    atomic_text(report_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))

    max_timeline = max([max(item["realRequests"], item["syntheticRequests"]) for item in timeline] + [1])
    timeline_html = "".join(
        """<div class="hour" aria-label="{hour}，真实 {real} 个请求，性能测试 {test} 个请求">
        <div class="hour-bars"><i class="real-bar" style="height:{real_height}%"></i><i class="test-bar" style="height:{test_height}%"></i></div>
        <span>{hour_label}</span></div>""".format(
            hour=html.escape(item["hour"]), real=item["realRequests"], test=item["syntheticRequests"],
            real_height=max(2, round(item["realRequests"] / max_timeline * 100)) if item["realRequests"] else 0,
            test_height=max(2, round(item["syntheticRequests"] / max_timeline * 100)) if item["syntheticRequests"] else 0,
            hour_label=html.escape(item["hour"][:2]) if int(item["hour"][:2]) % 3 == 0 else "",
        ) for item in timeline
    )
    max_category_bytes = max([item["bytes"] for item in categories] + [1])
    category_html = "".join(
        """<li><div class="row-head"><span><b>{label}</b><small>{requests} 个请求 · 平均 {average}</small></span>
        <strong>{bytes}</strong></div><div class="meter"><i style="width:{width}%"></i></div></li>""".format(
            label=html.escape(item["label"]), requests=item["requests"], average=human_duration(item["averageMs"]),
            bytes=human_bytes(item["bytes"]), width=max(1, round(item["bytes"] / max_category_bytes * 100)),
        ) for item in categories
    ) or '<li class="empty">过去 24 小时还没有真实资源请求。</li>'
    popular_html = "".join(
        """<li><span><b>{label}</b><small>{path}</small></span><strong>{requests} 次</strong></li>""".format(
            label=html.escape(item["label"]), path=html.escape(normalized_route(item["path"])), requests=item["requests"]
        ) for item in popular_pages
    ) or '<li class="empty">还没有可展示的真实页面访问。</li>'
    slow_html = "".join(
        """<li><span><b>{label}</b><small>{category} · {bytes}</small></span><strong>{duration}</strong></li>""".format(
            label=html.escape(item["label"]), category=html.escape(item["categoryLabel"]),
            bytes=human_bytes(item["bytes"]), duration=human_duration(item["averageMs"]),
        ) for item in slow_paths
    ) or '<li class="empty">没有需要留意的慢请求。</li>'
    bandwidth_width = max(1, real["bandwidthPercent"]) if real["peakMbps"] else 0
    status_icon = "✓" if status == "normal" else ("·" if status == "quiet" else "!")
    window_html = "".join(
        """<div><strong>{label}</strong><small>{requests} 请求 · P50/P95/P99 {p50}/{p95}/{p99} ms<br>普通 {normal} · 合成 {synthetic} · 健康 {health} · 大媒体 {large}</small></div>""".format(
            label=html.escape(value["label"]), requests=value["requests"],
            p50=value["latencyMs"]["p50"], p95=value["latencyMs"]["p95"], p99=value["latencyMs"]["p99"],
            normal=value["traffic"]["normal"]["requests"], synthetic=value["traffic"]["synthetic"]["requests"],
            health=value["traffic"]["health"]["requests"], large=value["traffic"]["largeMedia"]["requests"],
        ) for value in windows.values()
    )
    outcome_labels = {
        "success": "成功",
        "client_error": "访客请求错误",
        "capacity_rejection": "容量拒绝",
        "server_error": "源站故障",
        "server_error_unclassified": "未分类服务错误",
        "synthetic": "性能测试",
        "health": "健康检查",
    }
    outcome_html = "".join(
        "<div><strong>{}</strong><small>{} 个请求</small></div>".format(
            html.escape(outcome_labels.get(key, key)), value
        )
        for key, value in sorted(windows["24h"]["outcomes"].items())
    ) or "<div><strong>暂无结果</strong><small>0 个请求</small></div>"

    document = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OurNotes 站点状态</title><link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22><text y=%2226%22 font-size=%2228%22>◉</text></svg>"><style>
:root{{--ink:#20252d;--muted:#68717f;--line:#dce2e8;--paper:#f5f8fa;--surface:#fff;--blue:#2769a8;--blue-soft:#dcecf8;--green:#287c5a;--green-soft:#dff3e8;--amber:#a46616;--amber-soft:#fff0d2;--red:#aa3941;--red-soft:#fde5e7;--test:#9099a5;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55}}
.shell{{width:min(1180px,calc(100% - 40px));margin:0 auto;padding:38px 0 64px}}header{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}}
.brand small{{display:block;color:var(--blue);font:700 12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.12em}}h1{{font-size:clamp(28px,4vw,46px);line-height:1.05;margin:8px 0 0;letter-spacing:-.04em}}.updated{{color:var(--muted);font-size:13px;text-align:right}}
.verdict{{display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:center;border:1px solid var(--line);border-left:7px solid var(--green);background:var(--surface);padding:20px 22px;margin-bottom:18px;box-shadow:0 10px 30px rgba(38,58,76,.06)}}
.verdict.attention,.verdict.quiet{{border-left-color:var(--amber)}}.verdict.incident{{border-left-color:var(--red)}}.verdict-mark{{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;background:var(--green-soft);color:var(--green);font-size:24px;font-weight:800}}.attention .verdict-mark,.quiet .verdict-mark{{background:var(--amber-soft);color:var(--amber)}}.incident .verdict-mark{{background:var(--red-soft);color:var(--red)}}
.verdict h2{{margin:0 0 3px;font-size:20px}}.verdict p{{margin:0;color:var(--muted)}}.window{{white-space:nowrap;color:var(--muted);font-size:13px}}
.metrics{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border:1px solid var(--line);background:var(--surface);margin-bottom:18px}}.metric{{padding:18px;border-right:1px solid var(--line)}}.metric:last-child{{border:0}}.metric span{{display:block;color:var(--muted);font-size:13px}}.metric strong{{display:block;font:700 clamp(22px,3vw,32px) ui-monospace,SFMono-Regular,Menlo,monospace;margin:5px 0 3px;letter-spacing:-.04em}}.metric small{{color:var(--muted)}}
.bandwidth{{background:#e8edf1;height:7px;margin-top:9px;overflow:hidden}}.bandwidth i{{display:block;height:100%;background:var(--blue)}}
.panel-grid{{display:grid;grid-template-columns:1.35fr .65fr;gap:18px;margin-bottom:18px}}.panel{{background:var(--surface);border:1px solid var(--line);padding:22px}}.panel h2{{font-size:18px;margin:0}}.panel-heading{{display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:18px}}.panel-heading p{{margin:0;color:var(--muted);font-size:13px}}
.timeline{{display:grid;grid-template-columns:repeat(24,minmax(12px,1fr));gap:5px;height:150px;align-items:end;border-bottom:1px solid var(--line);padding-top:12px}}.hour{{height:100%;display:grid;grid-template-rows:1fr 18px;min-width:0}}.hour-bars{{display:flex;gap:2px;align-items:end;height:100%}}.hour-bars i{{display:block;flex:1;min-height:0}}.real-bar{{background:var(--blue)}}.test-bar{{background:var(--test)}}.hour span{{font:10px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);text-align:center;padding-top:4px}}.legend{{display:flex;gap:18px;margin-top:12px;color:var(--muted);font-size:12px}}.legend i{{display:inline-block;width:9px;height:9px;margin-right:6px;background:var(--blue)}}.legend .test-key{{background:var(--test)}}
.test-box{{background:#f1f3f5;border:1px solid var(--line);padding:18px}}.test-box h2{{margin:0 0 6px;font-size:16px}}.test-box p{{margin:0 0 16px;color:var(--muted);font-size:13px}}.test-numbers{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.test-numbers strong{{display:block;font:700 22px ui-monospace,SFMono-Regular,Menlo,monospace}}.test-numbers small{{color:var(--muted)}}
.lists{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:18px}}ul{{list-style:none;margin:0;padding:0}}.rows li{{padding:12px 0;border-top:1px solid var(--line)}}.rows li:first-child{{border-top:0}}.row-head,.rows li{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.rows b{{display:block;font-size:14px}}.rows small{{display:block;color:var(--muted);font-size:12px;word-break:break-all}}.rows strong{{white-space:nowrap;font:700 13px ui-monospace,SFMono-Regular,Menlo,monospace}}.meter{{height:5px;background:#edf1f4;margin-top:7px;width:100%}}.meter i{{height:100%;display:block;background:var(--blue)}}.resource-list li{{display:block}}.empty{{color:var(--muted);font-size:13px}}
details{{background:var(--surface);border:1px solid var(--line);padding:18px 20px}}summary{{cursor:pointer;font-weight:700}}.terms{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px 24px;margin-top:16px}}.terms p{{margin:0;color:var(--muted);font-size:13px}}.terms b{{color:var(--ink)}}
.footer{{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:14px}}a{{color:var(--blue)}}
@media(max-width:850px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.metric{{border-bottom:1px solid var(--line)}}.panel-grid,.lists{{grid-template-columns:1fr}}.verdict{{grid-template-columns:auto 1fr}}.window{{grid-column:2}}}}
@media(max-width:540px){{.shell{{width:min(100% - 24px,1180px);padding-top:24px}}header{{align-items:flex-start;display:block}}.updated{{text-align:left;margin-top:10px}}.verdict{{padding:16px;gap:12px}}.metrics{{grid-template-columns:1fr 1fr}}.metric{{padding:14px}}.panel{{padding:16px;overflow:hidden}}.timeline{{min-width:620px}}.timeline-wrap{{overflow-x:auto;padding-bottom:6px}}.terms{{grid-template-columns:1fr}}.footer{{display:block}}}}
</style></head><body><main class="shell">
<header><div class="brand"><small>OURNOTES / SITE WATCH</small><h1>站点状态</h1></div><div class="updated">北京时间 {generated}<br>数据范围：最近 24 小时</div></header>
<section class="verdict {status}"><div class="verdict-mark" aria-hidden="true">{status_icon}</div><div><h2>{status_label}</h2><p>{conclusion}</p></div><span class="window">每 5 分钟自动更新</span></section>
<section class="metrics" aria-label="真实访问概况">
<div class="metric"><span>真实页面访问</span><strong>{page_views}</strong><small>打开网页的次数，不含图片和压测</small></div>
<div class="metric"><span>近似访客</span><strong>{visitors}</strong><small>按匿名网络地址估算，不是注册用户</small></div>
<div class="metric"><span>真实下行流量</span><strong>{real_bytes}</strong><small>已排除性能测试</small></div>
<div class="metric"><span>服务器错误</span><strong>{server_errors}</strong><small>HTTP 5xx；0 表示服务端正常</small></div>
<div class="metric"><span>一分钟出口峰值（约）</span><strong>{peak_mbps} Mbps</strong><small>当前出口上限 3 Mbps</small><div class="bandwidth"><i style="width:{bandwidth_width}%"></i></div></div>
</section>
<section class="panel-grid"><article class="panel"><div class="panel-heading"><h2>24 小时请求变化</h2><p>蓝色是真实请求，灰色是性能测试</p></div><div class="timeline-wrap"><div class="timeline">{timeline}</div></div><div class="legend"><span><i></i>真实请求</span><span><i class="test-key"></i>性能测试</span></div></article>
<aside class="test-box"><h2>性能测试已单独计算</h2><p>这些请求由站内验收产生，不代表用户访问，也不会混入上面的真实指标。</p><div class="test-numbers"><div><strong>{test_requests}</strong><small>测试请求</small></div><div><strong>{test_bytes}</strong><small>测试流量</small></div><div><strong>{test_average}</strong><small>平均完成时间</small></div><div><strong>{test_errors}</strong><small>测试错误</small></div></div></aside></section>
<section class="lists"><article class="panel"><div class="panel-heading"><h2>流量花在哪里</h2><p>按真实下行排序</p></div><ul class="rows resource-list">{categories}</ul></article>
<article class="panel"><div class="panel-heading"><h2>访问了哪些页面</h2><p>只统计真实页面</p></div><ul class="rows">{popular}</ul></article>
<article class="panel"><div class="panel-heading"><h2>完成较慢的请求</h2><p>大媒体较慢通常是限速预期</p></div><ul class="rows">{slow}</ul></article></section>
<section class="panel"><div class="panel-heading"><h2>多窗口延迟与流量分类</h2><p>近似分位数来自请求耗时直方图</p></div><div class="test-numbers">{windows}</div></section>
<section class="panel"><div class="panel-heading"><h2>24 小时请求结果</h2><p>容量拒绝与源站故障分别统计</p></div><div class="test-numbers">{outcomes}</div></section>
<details><summary>这些数字是什么意思？</summary><div class="terms"><p><b>页面访问：</b>一次打开 HTML 页面。一个页面通常还会产生多次图片、脚本请求。</p><p><b>近似访客：</b>按日匿名化后的网络地址数量，只用于看趋势。</p><p><b>性能测试：</b>自动并发和浏览器验收，不是真实用户。</p><p><b>Range：</b>音视频只读取其中一段，属于正常播放行为。本期共有 {range_requests} 次。</p><p><b>304：</b>浏览器确认缓存仍有效，服务器没有重新发送文件。本期共有 {not_modified} 次。</p><p><b>服务器错误：</b>HTTP 5xx。404 等访客地址错误不会直接判定服务器故障。</p></div></details>
<div class="footer"><span>原始请求总数 {total_requests}（含资源、测试和健康检查）</span><span>采集延迟或数据异常时，页面继续保留最后一次成功结果。</span></div>
</main></body></html>""".format(
        generated=html.escape(generated_at_cst), status=status, status_icon=status_icon,
        status_label=html.escape(status_label), conclusion=html.escape(conclusion),
        page_views=real["pageViews"], visitors=real["visitors"], real_bytes=human_bytes(real["bytes"]),
        server_errors=real["serverErrors"], peak_mbps=real["peakMbps"], bandwidth_width=bandwidth_width,
        timeline=timeline_html, test_requests=synthetic["requests"], test_bytes=human_bytes(synthetic["bytes"]),
        test_average=human_duration(synthetic["averageMs"]), test_errors=synthetic["errors"],
        categories=category_html, popular=popular_html, slow=slow_html,
        range_requests=real["rangeRequests"], not_modified=real["notModified"], total_requests=totals["requests"],
        windows=window_html, outcomes=outcome_html,
    )
    atomic_text(report_dir / "index.html", document)

    csv_path = report_dir / "export.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["recordType", "window", "trafficClass", "path", "label", "category", "categoryLabel", "requests", "bytes", "errors", "averageMs", "p50Ms", "p95Ms", "p99Ms", "releaseId", "phase", "durationSeconds"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for window_key, window in windows.items():
            for class_name, values in window["traffic"].items():
                writer.writerow({
                    "recordType": "window", "window": window_key,
                    "trafficClass": class_name, "requests": values["requests"],
                    "bytes": values["bytes"], "errors": values["errors"],
                    "p50Ms": values["latencyMs"]["p50"],
                    "p95Ms": values["latencyMs"]["p95"],
                    "p99Ms": values["latencyMs"]["p99"],
                })
        for item in top_paths:
            writer.writerow({"recordType": "path", **item})
        for event in deployment_events["events"]:
            for phase, duration in event.get("phases", {}).items():
                writer.writerow({
                    "recordType": "deployment",
                    "releaseId": event.get("releaseId"),
                    "phase": phase,
                    "durationSeconds": duration,
                })
    os.chmod(str(csv_path), 0o644)
    print(json.dumps({"status": status, "real": real, "synthetic": synthetic}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
