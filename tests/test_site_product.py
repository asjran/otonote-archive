import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.site_product import copy_media, prepare_public_data


class SiteProductTest(unittest.TestCase):
    def test_public_pruning_keeps_source_hardlinks_and_core_search_intact(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OURNOTES_SITE_PROFILE": "v1"}):
            root = Path(tmp)
            source = root / "source.json"
            source.write_text(json.dumps({"entries": [{"type": "story"}, {"type": "music"}]}))
            public = root / "public"
            public.mkdir()
            os.link(source, public / "unified-search-index.json")
            (public / "story-database.json").write_text("{}")
            (public / "game-database.json").write_text("{}")
            prepare_public_data(public)
            self.assertEqual(len(json.loads(source.read_text())["entries"]), 2)
            self.assertEqual(json.loads((public / "unified-search-index.json").read_text())["entries"], [{"type": "music"}])
            self.assertFalse((public / "story-database.json").exists())
            self.assertTrue((public / "game-database.json").exists())

    def test_media_copy_excludes_archive_without_removing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["originals", "live2d", "device-archive", "story-resources"]:
                path = root / "source" / name
                path.mkdir(parents=True)
                (path / "asset.bin").write_bytes(b"asset")
            copy_media(root / "source", root / "candidate")
            self.assertEqual(list(p.name for p in (root / "candidate").iterdir()), ["originals"])
            self.assertTrue((root / "source/live2d/asset.bin").exists())

    def test_media_index_does_not_advertise_unpublished_audio(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OURNOTES_SITE_PROFILE": "v1"}):
            root = Path(tmp)
            records = [{"id": "card", "url": "/media/originals/card.png"}, {"id": "song", "url": "/media/music/song.m4a"}]
            (root / "media-index.json").write_text(json.dumps({"records": records}))
            prepare_public_data(root)
            self.assertEqual(json.loads((root / "media-index.json").read_text())["records"], records[:1])

    def test_bgm_media_survives_publication_copy_and_index_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bgm = root / 'source/bgm'
            bgm.mkdir(parents=True)
            (bgm / 'home.m4a').write_bytes(b'bgm')
            copy_media(root / 'source', root / 'candidate')
            self.assertEqual((root / 'candidate/bgm/home.m4a').read_bytes(), b'bgm')
            data = root / 'data'
            data.mkdir()
            record = {'id': 'bgm-home', 'url': '/media/bgm/home.m4a'}
            (data / 'media-index.json').write_text(json.dumps({'records': [record]}))
            (data / 'bgm.json').write_text('{}')
            prepare_public_data(data)
            self.assertEqual(json.loads((data / 'media-index.json').read_text())['records'], [record])
            self.assertTrue((data / 'bgm.json').is_file())
