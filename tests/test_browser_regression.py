from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_MATRIX = Path(os.environ.get("OURNOTES_TEST_DIST", REPO_ROOT / "output/release-builds/global-production-current/site"))


def regression_routes() -> list[str]:
    completed = subprocess.run(
        ["node", "tools/browser_regression.cjs", "--list-routes"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class BrowserRegressionTest(unittest.TestCase):
    def test_regression_report_binds_the_current_git_head(self) -> None:
        source = (REPO_ROOT / "tools/browser_regression.cjs").read_text(
            encoding="utf-8"
        )
        self.assertIn("function resolveGitHead()", source)
        self.assertIn("gitHead: resolveGitHead()", source)

    def test_regression_manifest_has_unique_product_routes(self) -> None:
        routes = regression_routes()
        # Current Global product manifest replaced the retired archive routes.
        expected = 25
        self.assertEqual(len(routes), expected)
        self.assertEqual(len(set(routes)), expected)
        self.assertTrue(all(route.startswith("/global/zh-CN/") for route in routes))
        self.assertTrue({"/global/zh-CN/events/", "/global/zh-CN/stories/",
                         "/global/zh-CN/tools/optimizer/"}.issubset(routes))

    @unittest.skipUnless(DIST_MATRIX.is_dir(), "requires a built site matrix")
    def test_regression_manifest_routes_exist_in_built_matrix(self) -> None:
        routes = regression_routes()
        for route in routes:
            target = DIST_MATRIX / route.lstrip("/") / "index.html"
            self.assertTrue(target.is_file(), route)


if __name__ == "__main__":
    unittest.main()
