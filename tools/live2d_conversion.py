"""Pure Unity Cubism conversion helpers, adapted from the former converter.

Only recognized parameter curves are exported; unsupported bindings remain visible
in the conversion report. Streamed keys use linear interpolation, not game tangents.
"""
from __future__ import annotations
import re
import math
import struct
import zlib
from pathlib import Path
from typing import Any, Mapping

BLEND_NAMES = {0: "Add", 1: "Multiply", 2: "Overwrite"}
COMPONENT_NAMES = {0: "X", 1: "Y", 2: "Angle"}
PARAMETER_VALUE_ATTRIBUTE = zlib.crc32(b"Value") & 0xFFFFFFFF
MOTION_DIRECTION = re.compile(r"^(?P<family>.+)_(?P<direction>[CLR])$")
DEFAULT_IDLE_FAMILIES = frozenset({"mtn_idle01", "mtn_idle_01"})


def describe_motion(
    source_name: str,
    *,
    idle_families: frozenset[str] = DEFAULT_IDLE_FAMILIES,
) -> dict[str, str | None]:
    """Return the stable model3 group and visitor-facing motion coordinates."""

    match = MOTION_DIRECTION.fullmatch(source_name)
    family = match.group("family") if match else source_name
    direction = match.group("direction") if match else None
    return {
        "sourceName": source_name,
        "family": family,
        "direction": direction,
        "group": "UserIdle" if family in idle_families else family,
    }


def build_model3(
    model_name: str,
    textures: list[str],
    expressions: list[str],
    *,
    physics: str | None = None,
    motions: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    references: dict[str, Any] = {
        "Moc": f"{model_name}.moc3",
        "Textures": textures,
    }
    if expressions:
        references["Expressions"] = [
            {"Name": Path(path).stem.removesuffix(".exp3"), "File": path}
            for path in expressions
        ]
    if physics:
        references["Physics"] = physics
    if motions:
        references["Motions"] = {
            group: [{"File": path} for path in paths]
            for group, paths in motions.items()
            if paths
        }
    return {
        "Version": 3,
        "FileReferences": references,
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
        ],
    }


def build_expression3(tree: Mapping[str, Any]) -> dict[str, Any]:
    parameters = []
    for item in tree.get("Parameters", []):
        if not isinstance(item, Mapping) or not item.get("Id"):
            continue
        parameters.append({
            "Id": str(item["Id"]),
            "Value": float(item.get("Value") or 0),
            "Blend": BLEND_NAMES.get(int(item.get("Blend") or 0), "Add"),
        })
    return {
        "Type": "Live2D Expression",
        "FadeInTime": float(tree.get("FadeInTime") or 0),
        "FadeOutTime": float(tree.get("FadeOutTime") or 0),
        "Parameters": parameters,
    }


def _normalization(value: Mapping[str, Any]) -> dict[str, float]:
    return {
        "Minimum": float(value.get("Minimum") or 0),
        "Maximum": float(value.get("Maximum") or 0),
        "Default": float(value.get("Default") or 0),
    }


def build_physics3(tree: Mapping[str, Any]) -> dict[str, Any]:
    settings: list[dict[str, Any]] = []
    for index, rig in enumerate((tree.get("_rig") or {}).get("SubRigs", [])):
        inputs = [{
            "Source": {"Target": "Parameter", "Id": str(item.get("SourceId") or "")},
            "Weight": float(item.get("Weight") or 0),
            "Type": COMPONENT_NAMES.get(int(item.get("SourceComponent") or 0), "X"),
            "Reflect": bool(item.get("IsInverted")),
        } for item in rig.get("Input", [])]
        outputs = []
        for item in rig.get("Output", []):
            component = int(item.get("SourceComponent") or 0)
            translation = item.get("TranslationScale") or {}
            scale = item.get("AngleScale") if component == 2 else translation.get("x" if component == 0 else "y")
            outputs.append({
                "Destination": {"Target": "Parameter", "Id": str(item.get("DestinationId") or "")},
                "VertexIndex": int(item.get("ParticleIndex") or 0),
                "Scale": float(scale or 0),
                "Weight": float(item.get("Weight") or 0),
                "Type": COMPONENT_NAMES.get(component, "X"),
                "Reflect": bool(item.get("IsInverted")),
            })
        vertices = [{
            "Position": {
                "X": float((item.get("InitialPosition") or {}).get("x") or 0),
                "Y": float((item.get("InitialPosition") or {}).get("y") or 0),
            },
            "Mobility": float(item.get("Mobility") or 0),
            "Delay": float(item.get("Delay") or 0),
            "Acceleration": float(item.get("Acceleration") or 0),
            "Radius": float(item.get("Radius") or 0),
        } for item in rig.get("Particles", [])]
        normalization = rig.get("Normalization") or {}
        settings.append({
            "Id": f"PhysicsSetting{index + 1}",
            "Name": str(rig.get("Name") or f"Physics {index + 1}"),
            "Input": inputs,
            "Output": outputs,
            "Vertices": vertices,
            "Normalization": {
                "Position": _normalization(normalization.get("Position") or {}),
                "Angle": _normalization(normalization.get("Angle") or {}),
            },
        })
    return {
        "Version": 3,
        "Meta": {
            "PhysicsSettingCount": len(settings),
            "TotalInputCount": sum(len(item["Input"]) for item in settings),
            "TotalOutputCount": sum(len(item["Output"]) for item in settings),
            "VertexCount": sum(len(item["Vertices"]) for item in settings),
            "EffectiveForces": {"Gravity": {"X": 0, "Y": -1}, "Wind": {"X": 0, "Y": 0}},
        },
        "PhysicsSettings": settings,
    }


def _float_from_uint(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def _streamed_frames(tree: Mapping[str, Any]) -> list[tuple[float, dict[int, float]]]:
    values = (
        ((tree.get("m_MuscleClip") or {}).get("m_Clip") or {})
        .get("data", {})
        .get("m_StreamedClip", {})
        .get("data", [])
    )
    frames: list[tuple[float, dict[int, float]]] = []
    cursor = 0
    while cursor + 1 < len(values):
        time = _float_from_uint(int(values[cursor]))
        key_count = int(values[cursor + 1])
        cursor += 2
        if cursor + key_count * 5 > len(values):
            raise ValueError("AnimationClip streamed curve payload is truncated")
        keys: dict[int, float] = {}
        for _ in range(key_count):
            index = int(values[cursor])
            # Unity StreamedKey stores four polynomial coefficients; the fourth
            # coefficient is the exact value at this keyframe.
            keys[index] = _float_from_uint(int(values[cursor + 4]))
            cursor += 5
        if math.isfinite(time) and time >= 0:
            frames.append((float(time), keys))
    return frames


def _curve_points(
    tree: Mapping[str, Any],
    duration: float,
) -> dict[int, list[tuple[float, float]]]:
    clip = (
        ((tree.get("m_MuscleClip") or {}).get("m_Clip") or {})
        .get("data", {})
    )
    streamed = clip.get("m_StreamedClip") or {}
    frames = _streamed_frames(tree)
    streamed_count = int(streamed.get("curveCount") or (
        max((index for _, keys in frames for index in keys), default=-1) + 1
    ))
    points: dict[int, list[tuple[float, float]]] = {}
    for time, keys in frames:
        for index, value in keys.items():
            curve = points.setdefault(index, [])
            if curve and curve[-1][0] == time:
                curve[-1] = (time, value)
            else:
                curve.append((time, value))
    dense = clip.get("m_DenseClip") or {}
    dense_count = int(dense.get("m_CurveCount") or 0)
    dense_frames = int(dense.get("m_FrameCount") or 0)
    dense_values = dense.get("m_SampleArray") or []
    sample_rate = float(dense.get("m_SampleRate") or tree.get("m_SampleRate") or 30)
    begin_time = float(dense.get("m_BeginTime") or 0)
    if dense_count and len(dense_values) >= dense_count * dense_frames:
        for frame in range(dense_frames):
            time = begin_time + frame / sample_rate
            for curve_index in range(dense_count):
                index = streamed_count + curve_index
                value = float(dense_values[frame * dense_count + curve_index])
                points.setdefault(index, []).append((time, value))
    constants = (clip.get("m_ConstantClip") or {}).get("data", [])
    constant_offset = streamed_count + dense_count
    for curve_index, value in enumerate(constants):
        point = float(value)
        points[constant_offset + curve_index] = (
            [(0.0, point), (duration, point)]
            if duration > 0
            else [(0.0, point)]
        )
    return points


def convert_animation_clip(
    tree: Mapping[str, Any],
    parameter_bindings: Mapping[int, str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    bindings = (tree.get("m_ClipBindingConstant") or {}).get("genericBindings", [])
    resolved: dict[int, str] = {}
    unknown: list[dict[str, int]] = []
    for index, binding in enumerate(bindings):
        path = int(binding.get("path") or 0)
        attribute = int(binding.get("attribute") or 0)
        parameter_id = parameter_bindings.get(path)
        if attribute == PARAMETER_VALUE_ATTRIBUTE and parameter_id:
            resolved[index] = parameter_id
        else:
            unknown.append({
                "index": index,
                "path": path,
                "attribute": attribute,
                "typeId": int(binding.get("typeID") or 0),
            })
    report: dict[str, Any] = {
        "name": str(tree.get("m_Name") or "motion"),
        "state": "unsupported_curve_binding",
        "bindingCount": len(bindings),
        "curveCount": 0,
        "unknownBindings": unknown,
    }
    if not resolved or unknown:
        return None, report
    muscle = tree.get("m_MuscleClip") or {}
    duration = float(muscle.get("m_StopTime") or 0)
    available_points = _curve_points(tree, duration)
    points: dict[int, list[tuple[float, float]]] = {
        index: available_points.get(index, [])
        for index in resolved
    }
    curves: list[dict[str, Any]] = []
    for index, parameter_id in resolved.items():
        curve_points = points[index]
        if not curve_points:
            unknown.append({
                "index": index,
                "path": int(bindings[index].get("path") or 0),
                "attribute": int(bindings[index].get("attribute") or 0),
                "typeId": int(bindings[index].get("typeID") or 0),
            })
            continue
        segments: list[float | int] = [
            round(curve_points[0][0], 6),
            round(curve_points[0][1], 6),
        ]
        for time, value in curve_points[1:]:
            # Linear segments preserve every serialized key value and avoid
            # inventing tangents that are not represented by motion3.
            segments.extend([0, round(time, 6), round(value, 6)])
        curves.append({
            "Target": "Parameter",
            "Id": parameter_id,
            "Segments": segments,
        })
    if unknown or not curves:
        report["unknownBindings"] = unknown
        return None, report
    duration = float(duration or max(
        (point[0] for curve in points.values() for point in curve),
        default=0,
    ))
    total_points = sum((len(curve["Segments"]) + 1) // 3 for curve in curves)
    result = {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": float(tree.get("m_SampleRate") or 30),
            "Loop": bool(muscle.get("m_LoopTime")),
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": sum(
                max(0, (len(curve["Segments"]) - 2) // 3)
                for curve in curves
            ),
            "TotalPointCount": total_points,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
    }
    report.update({
        "state": "supported",
        "curveCount": len(curves),
        "unknownBindings": [],
        "duration": duration,
        "mapping": "unity_streamed_key_linear_v1",
    })
    return result, report


def convert_motion_library(
    animation_clips: Mapping[str, Mapping[str, Any]],
    parameter_bindings: Mapping[int, str],
    *,
    publish: bool,
) -> dict[str, Any]:
    """Convert and classify a model's complete motion library."""

    motion_groups: dict[str, list[str]] = {}
    motions: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    supported_count = 0
    blocked_count = 0
    for source_name in sorted(animation_clips):
        motion, report = convert_animation_clip(
            animation_clips[source_name],
            parameter_bindings,
        )
        descriptor = describe_motion(source_name)
        report.update({
            "family": descriptor["family"],
            "direction": descriptor["direction"],
            "group": descriptor["group"],
        })
        reports.append(report)
        if motion is None:
            blocked_count += 1
            continue
        supported_count += 1
        if not publish:
            continue
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_name)
        filename = f"motions/{safe_name}.motion3.json"
        group = str(descriptor["group"])
        group_files = motion_groups.setdefault(group, [])
        index = len(group_files)
        group_files.append(filename)
        payloads[filename] = motion
        motions.append({
            "id": source_name,
            **descriptor,
            "index": index,
            "file": filename,
            "duration": float(report.get("duration") or 0),
            "curveCount": int(report.get("curveCount") or 0),
        })
    return {
        "sourceMotionCount": len(animation_clips),
        "supportedMotionCount": supported_count,
        "blockedMotionCount": blocked_count,
        "motionGroups": motion_groups,
        "motions": motions,
        "motionReports": reports,
        "payloads": payloads,
    }
