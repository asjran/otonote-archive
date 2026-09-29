"""Compile OUR NOTES gzip scores into client-runtime-equivalent projections."""

from __future__ import annotations

import gzip
import json
import math
from bisect import bisect_right
from typing import Any, Callable


TICK_RESOLUTION = 480
SLIDE_COMBO_TICK_UNIT = TICK_RESOLUTION // 2
SUPPORTED_SCORE_VERSION = 100
EASING_TYPES = {"linear", "in", "out"}
RUNTIME_ALGORITHM_VERSION = "ss-runtime-v1"


class ScoreChartError(ValueError):
    """Raised when a score cannot be safely normalized."""


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoreChartError(f"{label} must be a number")
    return float(value)


def _tick(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScoreChartError(f"{label} must be a non-negative integer")
    return value


def _easing_pair(value: Any, label: str) -> tuple[str, str]:
    if value is None:
        return "linear", "linear"
    if isinstance(value, str):
        pair = (value, value)
    elif (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        pair = (value[0], value[1])
    else:
        raise ScoreChartError(f"{label} must be a string or a two-item array")
    if pair[0] not in EASING_TYPES or pair[1] not in EASING_TYPES:
        raise ScoreChartError(f"{label} contains an unsupported easing type")
    return pair


def _time_converter(
    raw_events: list[dict[str, Any]],
) -> tuple[Callable[[int], float], list[dict[str, Any]]]:
    if not raw_events:
        raise ScoreChartError("score must contain at least one BPM event")

    ordered = sorted(raw_events, key=lambda event: _tick(event.get("t"), "BPM tick"))
    normalized: list[dict[str, Any]] = []
    elapsed = 0.0
    previous_tick = 0
    previous_bpm = 0.0

    for index, event in enumerate(ordered):
        tick = _tick(event.get("t"), "BPM tick")
        bpm = _number(event.get("bpm"), "BPM")
        if bpm <= 0:
            raise ScoreChartError("BPM must be greater than zero")
        if index == 0 and tick != 0:
            raise ScoreChartError("first BPM event must start at tick 0")
        if index and tick <= previous_tick:
            raise ScoreChartError("BPM ticks must be unique")
        if index:
            elapsed += (
                (tick - previous_tick)
                / TICK_RESOLUTION
                * 60.0
                / previous_bpm
            )
        normalized.append(
            {
                "tick": tick,
                "time": round(elapsed, 6),
                "bpm": bpm,
            }
        )
        previous_tick = tick
        previous_bpm = bpm

    ticks = [event["tick"] for event in normalized]

    def tick_to_time(tick: int) -> float:
        position = bisect_right(ticks, tick) - 1
        event = normalized[max(position, 0)]
        seconds = event["time"] + (
            (tick - event["tick"])
            / TICK_RESOLUTION
            * 60.0
            / event["bpm"]
        )
        return round(seconds, 6)

    return tick_to_time, normalized


def _normalize_note(
    raw_note: Any,
    index: int,
    tick_to_time: Callable[[int], float],
) -> dict[str, Any]:
    if not isinstance(raw_note, dict):
        raise ScoreChartError(f"note {index} must be an object")

    raw_type = raw_note.get("type")
    if raw_type in {"long", "guide"}:
        raw_nodes = raw_note.get("node")
        if not isinstance(raw_nodes, list) or len(raw_nodes) < 2:
            raise ScoreChartError(f"long note {index} must contain at least two nodes")
        nodes = []
        for node_index, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                raise ScoreChartError(
                    f"long note {index} node {node_index} must be an object"
                )
            tick = _tick(
                raw_node.get("t"),
                f"long note {index} node {node_index} tick",
            )
            raw_position = raw_node.get("pos")
            raw_size = raw_node.get("size")
            easing, easing_right = _easing_pair(
                raw_node.get("ease"),
                f"{raw_type} note {index} node {node_index} easing",
            )
            node = {
                "tick": tick,
                "time": tick_to_time(tick),
                "position": (
                    None
                    if raw_position == "auto"
                    else _number(
                        raw_position,
                        f"{raw_type} note {index} node {node_index} position",
                    )
                ),
                "size": (
                    None
                    if raw_size is None
                    else _number(
                        raw_size,
                        f"{raw_type} note {index} node {node_index} size",
                    )
                ),
                "easing": easing,
                "easingRight": easing_right,
                "visible": raw_node.get("visible") is not False,
                "critical": raw_node.get("crit") is True,
                "operateType": (
                    str(raw_node.get("type"))
                    if raw_node.get("type") in {"flick", "trace"}
                    else "normal"
                ),
            }
            if raw_node.get("type") == "flick":
                node["flick"] = True
                if raw_node.get("dir"):
                    node["direction"] = str(raw_node["dir"])
            nodes.append(node)
        return {"id": f"note-{index}", "type": raw_type, "nodes": nodes}

    tick = _tick(raw_note.get("t"), f"note {index} tick")
    note_type = raw_type if raw_type in {"flick", "trace"} else "tap"
    note = {
        "id": f"note-{index}",
        "type": note_type,
        "tick": tick,
        "time": tick_to_time(tick),
        "position": _number(raw_note.get("pos"), f"note {index} position"),
        "size": _number(raw_note.get("size"), f"note {index} size"),
        "critical": raw_note.get("crit") is True,
    }
    if note_type == "flick" and raw_note.get("dir"):
        note["direction"] = str(raw_note["dir"])
    return note


def _explicit_combo_events(
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project source judgements; Guide and control nodes are never markers."""

    pending: list[tuple[int, float, int, str, str, int | None]] = []
    source_order = 0
    for note in notes:
        note_id = note["id"]
        if note["type"] == "long":
            for node_index, node in enumerate(note["nodes"]):
                if not node["visible"]:
                    continue
                pending.append(
                    (
                        node["tick"],
                        node["time"],
                        source_order,
                        f"{note_id}:{node_index}",
                        note_id,
                        node_index,
                    )
                )
                source_order += 1
        elif note["type"] in {"tap", "flick", "trace"}:
            pending.append(
                (
                    note["tick"],
                    note["time"],
                    source_order,
                    note_id,
                    note_id,
                    None,
                )
            )
            source_order += 1

    pending.sort(key=lambda event: (event[0], event[2]))
    return [
        {
            "tick": tick,
            "time": time,
            "markerId": marker_id,
            "noteId": note_id,
            "nodeIndex": node_index,
            "kind": "explicit-judgement",
        }
        for tick, time, _, marker_id, note_id, node_index in pending
    ]


def _bpm_at_time_ms(
    bpm_events: list[dict[str, Any]],
    time_ms: int,
) -> float:
    event_times = [int(event["time"] * 1000) for event in bpm_events]
    position = bisect_right(event_times, time_ms) - 1
    return float(bpm_events[max(position, 0)]["bpm"])


def _slide_combo_candidates(
    notes: list[dict[str, Any]],
    bpm_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recreate the client's millisecond-domain eighth-note candidates."""

    candidates: list[dict[str, Any]] = []
    for note in notes:
        if note["type"] != "long":
            continue
        nodes = note["nodes"]
        boundaries = [
            nodes[0],
            *(
                node
                for node in nodes[1:-1]
                if node["visible"]
                and node["position"] is not None
                and node["size"] is not None
            ),
            nodes[-1],
        ]
        ordinal = 0
        for segment_index, (left, right) in enumerate(
            zip(boundaries, boundaries[1:])
        ):
            if (
                left["position"] is None
                or left["size"] is None
                or right["position"] is None
                or right["size"] is None
            ):
                raise ScoreChartError(
                    f"{note['id']} has an automatic slide boundary"
                )
            # MusicScoreNoteCreator stores node boundaries as integer
            # milliseconds.  Keep that truncation before iterating so a
            # rounded source timestamp cannot create a judgement on the end
            # boundary itself.
            current_ms = float(int(left["time"] * 1000))
            end_ms = int(right["time"] * 1000)
            while current_ms < end_ms:
                bpm = _bpm_at_time_ms(bpm_events, int(current_ms))
                current_ms += 30_000.0 / bpm
                target_ms = round(current_ms)
                if target_ms >= end_ms:
                    break
                duration = right["time"] - left["time"]
                progress = (
                    0.0
                    if duration <= 0
                    else (target_ms / 1000 - left["time"]) / duration
                )
                left_progress = _apply_easing(left["easing"], progress)
                right_progress = _apply_easing(
                    left["easingRight"],
                    progress,
                )
                left_edge = left["position"] + (
                    right["position"] - left["position"]
                ) * left_progress
                left_right_edge = left["position"] + left["size"]
                right_right_edge = right["position"] + right["size"]
                right_edge = left_right_edge + (
                    right_right_edge - left_right_edge
                ) * right_progress
                candidates.append(
                    {
                        "time": round(target_ms / 1000, 6),
                        "markerId": None,
                        "noteId": note["id"],
                        "nodeIndex": None,
                        "synthetic": True,
                        "kind": "slide-combo",
                        "syntheticOrdinal": ordinal,
                        "sourceSegment": segment_index,
                        "position": round(left_edge, 6),
                        "size": round(right_edge - left_edge, 6),
                    }
                )
                ordinal += 1
    return candidates


def _apply_easing(kind: str, progress: float) -> float:
    value = min(1.0, max(0.0, progress))
    if kind == "in":
        return value * value
    if kind == "out":
        return (2.0 - value) * value
    return value


def _hidden_topology_candidates(
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create topology-owned candidates used by guided score profiles.

    In the client converter, guided scores retain hidden connection objects
    while ordinary decorative hidden controls do not enter the Combo list.
    They remain synthetic and therefore never become browser markers.
    """

    if not any(note["type"] == "guide" for note in notes):
        return []
    result: list[dict[str, Any]] = []
    for note in notes:
        if note["type"] != "long":
            continue
        for node_index, node in enumerate(note["nodes"]):
            if node["visible"]:
                continue
            result.append(
                {
                    "time": node["time"],
                    "markerId": None,
                    "noteId": note["id"],
                    "nodeIndex": None,
                    "sourceControlNodeIndex": node_index,
                    "synthetic": True,
                    "kind": "topology-connection",
                    "position": node["position"],
                    "size": node["size"],
                }
            )
    return result


def _endpoint_groups(
    notes: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for note in notes:
        if note["type"] != "long":
            continue
        endpoint = note["nodes"][-1]
        key = (
            endpoint["tick"],
            endpoint["position"],
            endpoint["size"],
            endpoint["operateType"],
            endpoint["critical"],
        )
        groups.setdefault(key, []).append(
            {
                "noteId": note["id"],
                "nodeIndex": len(note["nodes"]) - 1,
                "time": endpoint["time"],
                "position": endpoint["position"],
                "size": endpoint["size"],
            }
        )
    return [group for group in groups.values() if len(group) > 1]


def _spans_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    if (
        left.get("position") is None
        or left.get("size") is None
        or right.get("position") is None
        or right.get("size") is None
    ):
        return 0.0
    return max(
        0.0,
        min(
            float(left["position"]) + float(left["size"]),
            float(right["position"]) + float(right["size"]),
        )
        - max(float(left["position"]), float(right["position"])),
    )


def _classify_skips(
    notes: list[dict[str, Any]],
    rhythmic: list[dict[str, Any]],
    endpoint_groups: list[list[dict[str, Any]]],
) -> tuple[set[int], list[dict[str, Any]]]:
    skipped: set[int] = set()
    diagnostics: list[dict[str, Any]] = []

    auto_keys = {
        (note["id"], round(node["time"] * 1000))
        for note in notes
        if note["type"] == "long"
        for node in note["nodes"]
        if node["position"] is None
    }
    for index, candidate in enumerate(rhythmic):
        if (candidate["noteId"], round(candidate["time"] * 1000)) in auto_keys:
            skipped.add(index)
            diagnostics.append(
                {
                    "kind": "skip",
                    "reason": "auto-control-collision",
                    "noteId": candidate["noteId"],
                    "time": candidate["time"],
                }
            )

    candidates_by_note: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, candidate in enumerate(rhythmic):
        candidates_by_note.setdefault(candidate["noteId"], []).append(
            (index, candidate)
        )

    for group in endpoint_groups:
        note_ids = [item["noteId"] for item in group]
        by_time: dict[int, list[tuple[int, dict[str, Any]]]] = {}
        for note_id in note_ids:
            for item in candidates_by_note.get(note_id, []):
                by_time.setdefault(round(item[1]["time"] * 1000), []).append(item)
        shared_times = [
            time
            for time, items in by_time.items()
            if len(items) >= 2
        ]
        if len(shared_times) > 1:
            shared_times = [max(shared_times)]
        for time in shared_times:
            same_time = by_time[time]
            if len(same_time) < 2:
                continue
            ordered = sorted(
                same_time,
                key=lambda item: (
                    item[1]["noteId"],
                    item[1].get("syntheticOrdinal", -1),
                ),
            )
            left_index, left = ordered[0]
            right_index, right = ordered[1]
            overlap = _spans_overlap(left, right)
            if overlap <= 0:
                continue
            if left_index in skipped and right_index in skipped:
                continue
            # Wide, short convergence consumes both connection Combo objects.
            # Narrow convergence keeps the stable first object and converts the
            # second to SkipSlideComboNote.
            remove = (
                (left_index, right_index)
                if overlap >= 4.0
                else (right_index,)
            )
            for index in remove:
                if index in skipped:
                    continue
                skipped.add(index)
                candidate = rhythmic[index]
                diagnostics.append(
                    {
                        "kind": "skip",
                        "reason": "converging-slide",
                        "noteId": candidate["noteId"],
                        "time": candidate["time"],
                        "overlap": round(overlap, 6),
                    }
                )
    return skipped, diagnostics


def _combo_events(
    notes: list[dict[str, Any]],
    bpm_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the runtime Combo list without a Master-derived target count."""

    explicit = _explicit_combo_events(notes)
    rhythmic = _slide_combo_candidates(notes, bpm_events)
    hidden = _hidden_topology_candidates(notes)
    endpoint_groups = _endpoint_groups(notes)
    skipped, skip_diagnostics = _classify_skips(
        notes,
        rhythmic,
        endpoint_groups,
    )

    merged_marker_ids: set[str] = set()
    merge_diagnostics: list[dict[str, Any]] = []
    explicit_marker_ids = {event["markerId"] for event in explicit}
    for group in endpoint_groups:
        marker_ids = [
            marker_id
            for item in group
            if (marker_id := f"{item['noteId']}:{item['nodeIndex']}")
            in explicit_marker_ids
        ]
        if len(marker_ids) < 2:
            continue
        merged_marker_ids.update(marker_ids[1:])
        merge_diagnostics.append(
            {
                "kind": "merge",
                "reason": "identical-slide-endpoint",
                "time": group[0]["time"],
                "markerIds": marker_ids,
            }
        )

    retained_explicit = [
        event
        for event in explicit
        if event["markerId"] not in merged_marker_ids
    ]
    retained_rhythmic = [
        event
        for index, event in enumerate(rhythmic)
        if index not in skipped
    ]
    combined = [*retained_explicit, *hidden, *retained_rhythmic]
    combined.sort(
        key=lambda event: (
            event["time"],
            bool(event.get("synthetic")),
            event["noteId"],
            event.get("nodeIndex") if event.get("nodeIndex") is not None else -1,
        )
    )
    combo_events = []
    for combo, event in enumerate(combined, start=1):
        normalized = {
            key: value
            for key, value in event.items()
            if key not in {"tick", "sourceSegment"}
        }
        normalized["combo"] = combo
        combo_events.append(normalized)
    diagnostics = {
        "explicitJudgementCount": len(explicit),
        "slideComboCandidateCount": len(rhythmic) + len(hidden),
        "skippedSlideComboCount": len(skipped),
        "mergedEndpointReduction": len(merged_marker_ids),
        "runtimeDiagnostics": [
            *skip_diagnostics,
            *merge_diagnostics,
        ],
    }
    expected_count = (
        diagnostics["explicitJudgementCount"]
        + diagnostics["slideComboCandidateCount"]
        - diagnostics["skippedSlideComboCount"]
        - diagnostics["mergedEndpointReduction"]
    )
    if len(combo_events) != expected_count:
        raise ScoreChartError(
            "runtime Combo conservation failed: "
            f"expected {expected_count}, compiled {len(combo_events)}"
        )
    return combo_events, diagnostics


def _density(judgement_times: list[float], duration: float) -> list[dict[str, Any]]:
    bucket_count = max(1, int(math.ceil(duration)))
    counts = [0] * bucket_count
    for time in judgement_times:
        counts[min(int(time), bucket_count - 1)] += 1
    return [
        {
            "start": float(index),
            "end": round(min(float(index + 1), duration), 6),
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def compile_music_score(
    payload: bytes,
) -> dict[str, Any]:
    """Return one validated, deterministic browser-facing score projection."""

    try:
        decoded = gzip.decompress(payload)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ScoreChartError(f"invalid gzip score payload: {exc}") from exc
    try:
        source = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoreChartError(f"invalid score JSON: {exc}") from exc

    if not isinstance(source, dict):
        raise ScoreChartError("score root must be an object")
    meta = source.get("meta")
    version = meta.get("version") if isinstance(meta, dict) else None
    if version != SUPPORTED_SCORE_VERSION:
        raise ScoreChartError(f"unsupported score version: {version!r}")
    score = source.get("score")
    if not isinstance(score, dict):
        raise ScoreChartError("score field must be an object")
    events = score.get("events")
    raw_notes = score.get("notes")
    if not isinstance(events, dict) or not isinstance(raw_notes, list):
        raise ScoreChartError("score must contain events and notes")

    raw_bpm = events.get("bpm")
    if not isinstance(raw_bpm, list) or not all(
        isinstance(event, dict) for event in raw_bpm
    ):
        raise ScoreChartError("BPM events must be an array")
    tick_to_time, bpm_events = _time_converter(raw_bpm)
    notes = [
        _normalize_note(raw_note, index, tick_to_time)
        for index, raw_note in enumerate(raw_notes)
    ]

    raw_signatures = events.get("sig", [])
    if not isinstance(raw_signatures, list):
        raise ScoreChartError("time signature events must be an array")
    time_signatures = []
    for raw_signature in raw_signatures:
        if not isinstance(raw_signature, dict):
            raise ScoreChartError("time signature event must be an object")
        tick = _tick(raw_signature.get("t"), "time signature tick")
        signature = raw_signature.get("sig")
        if (
            not isinstance(signature, list)
            or len(signature) != 2
            or not all(isinstance(value, int) and value > 0 for value in signature)
        ):
            raise ScoreChartError("time signature must contain two positive integers")
        time_signatures.append(
            {
                "tick": tick,
                "time": tick_to_time(tick),
                "numerator": signature[0],
                "denominator": signature[1],
            }
        )

    raw_skills = events.get("skill", [])
    raw_fever = events.get("fever", [])
    raw_calls = events.get("call", [])
    if not isinstance(raw_skills, list) or not isinstance(raw_fever, list):
        raise ScoreChartError("skill and FEVER events must be arrays")
    skill_timings = [
        tick_to_time(_tick(tick, "skill tick")) for tick in raw_skills
    ]
    fever_ranges = []
    for raw_range in raw_fever:
        if not isinstance(raw_range, list) or len(raw_range) != 2:
            raise ScoreChartError("FEVER range must contain start and end ticks")
        start_tick = _tick(raw_range[0], "FEVER start tick")
        end_tick = _tick(raw_range[1], "FEVER end tick")
        if end_tick < start_tick:
            raise ScoreChartError("FEVER range must not end before it starts")
        fever_ranges.append(
            {
                "start": tick_to_time(start_tick),
                "end": tick_to_time(end_tick),
            }
        )

    call_timings = []
    if not isinstance(raw_calls, list):
        raise ScoreChartError("call events must be an array")
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ScoreChartError("call event must be an object")
        tick = _tick(raw_call.get("t"), "call tick")
        call_timings.append(
            {
                "time": tick_to_time(tick),
                "pattern": raw_call.get("timing", []),
            }
        )

    combo_events, runtime_statistics = _combo_events(
        notes,
        bpm_events,
    )
    judgement_times = [event["time"] for event in combo_events]
    judgement_count = len(combo_events)
    note_extent_times = [
        time
        for note in notes
        for time in (
            [node["time"] for node in note["nodes"]]
            if "nodes" in note
            else [note["time"]]
        )
    ]
    event_times = [
        *skill_timings,
        *(value for item in fever_ranges for value in item.values()),
        *(event["time"] for event in bpm_events),
    ]
    duration = round(
        max([0.0, *judgement_times, *note_extent_times, *event_times]),
        6,
    )
    density = _density(judgement_times, duration)
    distinct_times = sorted(set(judgement_times))
    intervals = [
        right - left for left, right in zip(distinct_times, distinct_times[1:])
    ]
    simultaneous_count = len(judgement_times) - len(distinct_times)
    note_counts = {
        kind: sum(note["type"] == kind for note in notes)
        for kind in ("tap", "flick", "trace", "long")
    }
    peak_bucket = max(density, key=lambda item: item["count"])

    return {
        "meta": {
            "sourceVersion": version,
            "schemaVersion": 2,
            "tickResolution": TICK_RESOLUTION,
            "runtimeAlgorithmVersion": RUNTIME_ALGORITHM_VERSION,
        },
        "duration": duration,
        "bpmEvents": bpm_events,
        "timeSignatureEvents": time_signatures,
        "skillTimings": skill_timings,
        "feverRanges": fever_ranges,
        "callTimings": call_timings,
        "notes": notes,
        "paths": [
            {
                "id": note["id"],
                "kind": note["type"],
                "nodes": note["nodes"],
            }
            for note in notes
            if note["type"] in {"long", "guide"}
        ],
        "comboEvents": combo_events,
        "density": density,
        "statistics": {
            "noteCounts": note_counts,
            "judgementCount": judgement_count,
            "runtimeFullCombo": judgement_count,
            **runtime_statistics,
            "sourceJudgementCount": runtime_statistics[
                "explicitJudgementCount"
            ],
            "generatedJudgementCount": max(
                0,
                judgement_count
                - runtime_statistics["explicitJudgementCount"],
            ),
            "judgementCountDelta": (
                judgement_count
                - runtime_statistics["explicitJudgementCount"]
            ),
            "judgementCountSource": "client-runtime-reconstruction",
            "densitySource": "client-reconstructed-combo-timeline",
            "rhythmicCandidateCount": runtime_statistics[
                "slideComboCandidateCount"
            ],
            "guidePathCount": sum(
                note["type"] == "guide" for note in notes
            ),
            "autoControlNodeCount": sum(
                node["position"] is None
                for note in notes
                if note["type"] in {"long", "guide"}
                for node in note["nodes"]
            ),
            "longNodeCount": sum(
                len(note.get("nodes", []))
                for note in notes
                if note["type"] == "long"
            ),
            "bpm": {
                "min": min(event["bpm"] for event in bpm_events),
                "max": max(event["bpm"] for event in bpm_events),
            },
            "averageDensity": round(
                judgement_count / duration if duration else 0.0,
                3,
            ),
            "peakDensity": peak_bucket["count"],
            "peakWindowStart": peak_bucket["start"],
            "simultaneousCount": simultaneous_count,
            "minimumInterval": (
                round(min(intervals), 6) if intervals else None
            ),
        },
    }
