import tempfile
import unittest
from pathlib import Path

from tools.verify_site_product import verify


class VerifySiteProductTest(unittest.TestCase):
    def test_checks_references_and_closed_routes_in_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('<a href="/cards/">Cards</a><img srcset="/media/missing.png 2x">')
            (root / 'cards').mkdir()
            (root / 'cards/index.html').write_text('<a href="/">Home</a>')
            self.assertEqual(verify(root)['failures'], ['missing: /media/missing.png'])
            (root / 'media').mkdir()
            (root / 'media/missing.png').write_bytes(b'image')
            self.assertEqual(verify(root)['status'], 'passed')
            (root / 'stories').mkdir()
            (root / 'stories/index.html').write_text('Text stories')
            self.assertEqual(verify(root)['status'], 'passed')
            (root / 'resources').mkdir()
            (root / 'resources/index.html').write_text('Media archive')
            self.assertIn('closed route: resources/index.html', verify(root)['failures'])
