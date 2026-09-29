from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from tools.performance_budget import analyze_artifact, compare_reports


class PerformanceBudgetTest(unittest.TestCase):
    def test_reports_html_weight_by_route_and_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "jp/en/music/index.html"
            page.parent.mkdir(parents=True)
            page.write_text("<html>" + ("archive " * 100) + "</html>")
            script = root / "_astro/app.js"
            script.parent.mkdir()
            script.write_text("console.log('ok')")

            report = analyze_artifact(root)

            route = report["routes"]["jp/en/music/"]
            self.assertEqual(route["bytes"], page.stat().st_size)
            self.assertEqual(
                route["gzipBytes"],
                len(gzip.compress(page.read_bytes(), mtime=0)),
            )
            self.assertEqual(report["types"][".js"]["count"], 1)

    def test_compares_release_totals_and_route_growth(self) -> None:
        baseline = {
            "files": 2,
            "bytes": 100,
            "routes": {"jp/en/": {"bytes": 50, "gzipBytes": 20}},
        }
        current = {
            "files": 3,
            "bytes": 125,
            "routes": {"jp/en/": {"bytes": 75, "gzipBytes": 25}},
        }

        self.assertEqual(
            compare_reports(current, baseline),
            {
                "files": 1,
                "bytes": 25,
                "percentBytes": 25.0,
                "routes": {
                    "jp/en/": {
                        "bytes": 25,
                        "gzipBytes": 5,
                    }
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
