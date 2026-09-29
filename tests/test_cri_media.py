from __future__ import annotations

import unittest

from analysis.crypto.extract_cri_media import (
    parse_audio_quality,
    resolve_hca_key,
)


class CriMediaTest(unittest.TestCase):
    def test_defaults_hca_key_to_raw_cri_key(self) -> None:
        self.assertEqual(resolve_hca_key(123456789, None), 123456789)

    def test_explicit_hca_key_overrides_raw_cri_key(self) -> None:
        self.assertEqual(resolve_hca_key(123456789, 12345), 12345)

    def test_classifies_low_entropy_full_scale_audio_as_suspicious(self) -> None:
        quality = parse_audio_quality(
            """
            Peak level dB: 0.000265
            RMS level dB: -26.047972
            Peak count: 316.000000
            Entropy: 0.015268
            Number of samples: 263428
            """
        )

        self.assertEqual(quality["status"], "suspicious_decryption")
        self.assertFalse(quality["ok"])
        self.assertAlmostEqual(quality["peak_ratio"], 316 / 263428)

    def test_classifies_normal_dynamic_audio_as_audible(self) -> None:
        quality = parse_audio_quality(
            """
            Peak level dB: -0.675009
            RMS level dB: -16.528850
            Peak count: 2.000000
            Entropy: 0.505191
            Number of samples: 263428
            """
        )

        self.assertEqual(quality["status"], "audible")
        self.assertTrue(quality["ok"])

    def test_classifies_zero_pcm_as_silent_without_failing_decode(self) -> None:
        quality = parse_audio_quality(
            """
            Peak level dB: -inf
            RMS level dB: -inf
            Peak count: 2510736.000000
            Entropy: 0.000000
            Number of samples: 1255368
            """
        )

        self.assertEqual(quality["status"], "silent")
        self.assertTrue(quality["ok"])


if __name__ == "__main__":
    unittest.main()
