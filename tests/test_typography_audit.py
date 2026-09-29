import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.typography_audit import find_undersized_font_declarations


class TypographyAuditTests(unittest.TestCase):
    def test_reports_numeric_pixel_font_sizes_below_the_required_minimum(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stylesheet = Path(temporary_directory) / "sample.css"
            stylesheet.write_text(
                ".tiny { font-size: 9px; }\n"
                ".minimum { font-size: 12px; }\n"
                ".token { font-size: var(--text-metadata-size); }\n",
                encoding="utf-8",
            )

            self.assertEqual(
                find_undersized_font_declarations([stylesheet]),
                [
                    {
                        "path": str(stylesheet),
                        "line": 1,
                        "size_px": 9.0,
                        "source": ".tiny { font-size: 9px; }",
                    }
                ],
            )

    def test_site_stylesheets_keep_readable_text_at_twelve_pixels_or_larger(self):
        stylesheets = sorted((REPO_ROOT / "site/src/styles").glob("*.css"))
        self.assertTrue(stylesheets, "site stylesheet discovery must not be empty")
        self.assertEqual(find_undersized_font_declarations(stylesheets), [])


if __name__ == "__main__":
    unittest.main()
