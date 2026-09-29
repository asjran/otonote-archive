from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.private_content_guard import (  # noqa: E402
    PrivateContentError,
    verify_no_private_content,
)


class PrivateContentGuardTest(unittest.TestCase):
    def test_accepts_normal_public_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text("<h1>OurNotes</h1>")
            (root / "data").mkdir()
            (root / "data/catalog.json").write_text('{"schemaVersion": 1}')

            report = verify_no_private_content(root)

            self.assertEqual(report["filesScanned"], 2)

    def test_accepts_published_anontokyo_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            route = root / "anontokyo/staff-assignment"
            route.mkdir(parents=True)
            (route / "index.html").write_text(
                "Anon Tokyo Studio Global content experience",
                encoding="utf-8",
            )

            report = verify_no_private_content(root)

            self.assertEqual(report["status"], "clean")

    def test_rejects_private_route_and_content_marker_without_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            route = root / "private-preview/anontokyo"
            route.mkdir(parents=True)
            (route / "index.html").write_text("PRIVATE LOCAL PREVIEW")

            with self.assertRaises(PrivateContentError) as raised:
                verify_no_private_content(root)

            self.assertIn("private-preview/anontokyo", str(raised.exception))
            self.assertNotIn(str(root), str(raised.exception))

    def test_rejects_private_marker_inside_public_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            (root / "index.html").write_text("OurNotes")
            (root / "search.json").write_text(
                '{"route":"/private-preview/anontokyo/goods/"}'
            )

            with self.assertRaisesRegex(PrivateContentError, "search.json"):
                verify_no_private_content(root)


if __name__ == "__main__":
    unittest.main()
