from __future__ import annotations
import struct
import unittest
from tools.live2d_conversion import build_expression3, build_model3, build_physics3, convert_animation_clip, convert_motion_library, describe_motion

def float_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]

def streamed_frame(time: float, keys: list[tuple[int, float]]) -> list[int]:
    values = [float_bits(time), len(keys)]
    for index, value in keys:
        values.extend([index, 0, 0, 0, float_bits(value)])
    return values

class Live2DConversionTest(unittest.TestCase):
    def test_describes_motion_family_direction_and_idle_group_deterministically(self) -> None:
        self.assertEqual(
            describe_motion("mtn_idle01_C"),
            {
                "sourceName": "mtn_idle01_C",
                "family": "mtn_idle01",
                "direction": "C",
                "group": "UserIdle",
            },
        )
        self.assertEqual(
            describe_motion("mtn_smile01_R"),
            {
                "sourceName": "mtn_smile01_R",
                "family": "mtn_smile01",
                "direction": "R",
                "group": "mtn_smile01",
            },
        )
        self.assertEqual(
            describe_motion("mtn_action_01"),
            {
                "sourceName": "mtn_action_01",
                "family": "mtn_action_01",
                "direction": None,
                "group": "mtn_action_01",
            },
        )

    def test_converts_every_safe_clip_and_reports_blocked_clips_without_guessing(self) -> None:
        supported = {
            "m_Name": "mtn_idle01_C",
            "m_SampleRate": 30,
            "m_MuscleClip": {
                "m_StopTime": 1,
                "m_LoopTime": True,
                "m_Clip": {"data": {"m_StreamedClip": {"data": [
                    *streamed_frame(0, [(0, 0)]),
                    *streamed_frame(1, [(0, 1)]),
                    float_bits(float("inf")), 0,
                ]}}},
            },
            "m_ClipBindingConstant": {
                "genericBindings": [{
                    "path": 123,
                    "attribute": 3702945584,
                    "typeID": 114,
                }]
            },
        }
        blocked = {
            **supported,
            "m_Name": "mtn_unknown_C",
            "m_ClipBindingConstant": {
                "genericBindings": [{
                    "path": 999,
                    "attribute": 123,
                    "typeID": 114,
                }]
            },
        }

        library = convert_motion_library(
            {
                "mtn_unknown_C": blocked,
                "mtn_idle01_C": supported,
            },
            {123: "ParamAngleX"},
            publish=True,
        )

        self.assertEqual(library["sourceMotionCount"], 2)
        self.assertEqual(library["supportedMotionCount"], 1)
        self.assertEqual(library["blockedMotionCount"], 1)
        self.assertEqual(
            library["motionGroups"],
            {"UserIdle": ["motions/mtn_idle01_C.motion3.json"]},
        )
        self.assertEqual(
            library["motions"][0],
            {
                "id": "mtn_idle01_C",
                "sourceName": "mtn_idle01_C",
                "family": "mtn_idle01",
                "direction": "C",
                "group": "UserIdle",
                "index": 0,
                "file": "motions/mtn_idle01_C.motion3.json",
                "duration": 1.0,
                "curveCount": 1,
            },
        )
        self.assertEqual(
            library["motionReports"][1]["state"],
            "unsupported_curve_binding",
        )
        self.assertNotIn(
            "motions/mtn_unknown_C.motion3.json",
            library["payloads"],
        )

    def test_builds_minimal_web_model_with_blink_and_lipsync_groups(self) -> None:
        model = build_model3(
            "tomori",
            ["texture_00.png", "texture_01.png"],
            ["smile.exp3.json"],
            motions={"Idle": ["motions/idle.motion3.json"]},
        )
        self.assertEqual(model["Version"], 3)
        self.assertEqual(model["FileReferences"]["Moc"], "tomori.moc3")
        self.assertEqual(len(model["FileReferences"]["Textures"]), 2)
        self.assertEqual(
            model["FileReferences"]["Motions"]["Idle"][0]["File"],
            "motions/idle.motion3.json",
        )
        self.assertEqual(model["Groups"][0]["Name"], "EyeBlink")
        self.assertEqual(model["Groups"][1]["Name"], "LipSync")

    def test_maps_unity_expression_blends(self) -> None:
        expression = build_expression3({
            "FadeInTime": 0.5,
            "FadeOutTime": 1,
            "Parameters": [
                {"Id": "ParamA", "Value": 0.2, "Blend": 0},
                {"Id": "ParamB", "Value": 0.8, "Blend": 2},
            ],
        })
        self.assertEqual(expression["Parameters"][0]["Blend"], "Add")
        self.assertEqual(expression["Parameters"][1]["Blend"], "Overwrite")

    def test_maps_unity_physics_rig_to_physics3(self) -> None:
        physics = build_physics3({"_rig": {"SubRigs": [{
            "Name": "hair",
            "Input": [{"SourceId": "ParamAngleX", "Weight": 100, "SourceComponent": 0, "IsInverted": 0}],
            "Output": [{"DestinationId": "ParamHair", "ParticleIndex": 1, "AngleScale": 2, "Weight": 100, "SourceComponent": 2, "IsInverted": 1}],
            "Particles": [{"InitialPosition": {"x": 0, "y": 0}, "Mobility": 1, "Delay": 1, "Acceleration": 1, "Radius": 0}],
            "Normalization": {"Position": {"Minimum": -10, "Maximum": 10, "Default": 0}, "Angle": {"Minimum": -30, "Maximum": 30, "Default": 0}},
        }]}})
        self.assertEqual(physics["Version"], 3)
        self.assertEqual(physics["PhysicsSettings"][0]["Input"][0]["Type"], "X")
        self.assertTrue(physics["PhysicsSettings"][0]["Output"][0]["Reflect"])

    def test_converts_confirmed_parameter_bindings_to_linear_motion3_curves(self) -> None:
        clip = {
            "m_Name": "mtn_idle01_C",
            "m_SampleRate": 30,
            "m_MuscleClip": {
                "m_StopTime": 1,
                "m_LoopTime": True,
                "m_Clip": {"data": {"m_StreamedClip": {"data": [
                    *streamed_frame(-3.4028234663852886e38, [(0, 0)]),
                    *streamed_frame(0, [(0, 0)]),
                    *streamed_frame(0.5, [(0, 1)]),
                    *streamed_frame(1, [(0, 0)]),
                    float_bits(float("inf")), 0,
                ]}}},
            },
            "m_ClipBindingConstant": {
                "genericBindings": [{
                    "path": 123,
                    "attribute": 3702945584,
                    "typeID": 114,
                }]
            },
        }

        motion, report = convert_animation_clip(clip, {123: "ParamAngleX"})

        self.assertEqual(report["state"], "supported")
        self.assertEqual(report["curveCount"], 1)
        self.assertEqual(motion["Meta"]["Duration"], 1)
        self.assertTrue(motion["Meta"]["Loop"])
        self.assertEqual(motion["Curves"][0]["Id"], "ParamAngleX")
        self.assertEqual(
            motion["Curves"][0]["Segments"],
            [0.0, 0.0, 0, 0.5, 1.0, 0, 1.0, 0.0],
        )

    def test_rejects_unknown_animation_bindings_without_guessing(self) -> None:
        clip = {
            "m_Name": "unknown",
            "m_SampleRate": 30,
            "m_MuscleClip": {
                "m_StopTime": 1,
                "m_LoopTime": False,
                "m_Clip": {"data": {"m_StreamedClip": {"data": [
                    *streamed_frame(0, [(0, 1)]),
                    float_bits(float("inf")), 0,
                ]}}},
            },
            "m_ClipBindingConstant": {
                "genericBindings": [{
                    "path": 999,
                    "attribute": 123,
                    "typeID": 114,
                }]
            },
        }

        motion, report = convert_animation_clip(clip, {})

        self.assertIsNone(motion)
        self.assertEqual(report["state"], "unsupported_curve_binding")
        self.assertEqual(report["unknownBindings"][0]["path"], 999)

    def test_maps_constant_clip_values_after_streamed_curve_indices(self) -> None:
        clip = {
            "m_Name": "mixed",
            "m_SampleRate": 30,
            "m_MuscleClip": {
                "m_StopTime": 2,
                "m_LoopTime": False,
                "m_Clip": {"data": {
                    "m_StreamedClip": {
                        "curveCount": 1,
                        "data": [
                            *streamed_frame(0, [(0, 0)]),
                            *streamed_frame(2, [(0, 1)]),
                            float_bits(float("inf")), 0,
                        ],
                    },
                    "m_DenseClip": {
                        "m_CurveCount": 0,
                        "m_FrameCount": 0,
                        "m_SampleArray": [],
                    },
                    "m_ConstantClip": {"data": [0.75]},
                }},
            },
            "m_ClipBindingConstant": {
                "genericBindings": [
                    {"path": 1, "attribute": 3702945584, "typeID": 114},
                    {"path": 2, "attribute": 3702945584, "typeID": 114},
                ]
            },
        }

        motion, report = convert_animation_clip(
            clip,
            {1: "ParamAngleX", 2: "ParamEyeLOpen"},
        )

        self.assertEqual(report["state"], "supported")
        self.assertEqual(motion["Curves"][1]["Id"], "ParamEyeLOpen")
        self.assertEqual(
            motion["Curves"][1]["Segments"],
            [0.0, 0.75, 0, 2.0, 0.75],
        )

