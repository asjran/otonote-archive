from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.localization import (
    extract_localized_text,
    language_coverage,
    resolve_localized_text,
)


class LocalizedProjectionTest(unittest.TestCase):
    def test_retains_all_four_master_languages(self) -> None:
        localized = extract_localized_text(
            {
                "_simplifiedChinese": "简体",
                "_traditionalChinese": "繁體",
                "_japanese": "日本語",
                "_english": "English",
            }
        )

        self.assertEqual(
            localized,
            {
                "zh-CN": "简体",
                "zh-TW": "繁體",
                "ja": "日本語",
                "en": "English",
            },
        )

    def test_missing_locale_reports_the_actual_fallback_locale(self) -> None:
        resolved = resolve_localized_text(
            {"ja": "日本語", "en": "English"},
            "zh-CN",
        )

        self.assertEqual(resolved.text, "日本語")
        self.assertEqual(resolved.requested_locale, "zh-CN")
        self.assertEqual(resolved.actual_locale, "ja")
        self.assertTrue(resolved.used_fallback)

    def test_coverage_reports_missing_and_fallback_counts(self) -> None:
        report = language_coverage(
            [
                {"zh-CN": "一", "ja": "一"},
                {"ja": "二"},
            ],
            "zh-CN",
        )

        self.assertEqual(report["total"], 2)
        self.assertEqual(report["availableByLocale"]["zh-CN"], 1)
        self.assertEqual(report["fallbackCount"], 1)
        self.assertEqual(report["missingCount"], 0)


if __name__ == "__main__":
    unittest.main()
