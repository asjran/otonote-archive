from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.media_dedupe import MediaDedupeError, deduplicate_indexed_media


class MediaDedupeTest(unittest.TestCase):
    def test_verified_duplicate_media_becomes_one_physical_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            (media / "audio").mkdir(parents=True)
            payload = b"same verified media"
            first = media / "audio/first.flac"
            second = media / "audio/second.flac"
            first.write_bytes(payload)
            second.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            index = root / "media-index.json"
            index.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [
                            {
                                "tiers": {
                                    "original": {
                                        "url": "/media/audio/first.flac",
                                        "byteSize": len(payload),
                                        "sha256": digest,
                                    }
                                }
                            },
                            {
                                "tiers": {
                                    "original": {
                                        "url": "/media/audio/second.flac",
                                        "byteSize": len(payload),
                                        "sha256": digest,
                                    }
                                }
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = deduplicate_indexed_media(media, index)

            self.assertEqual(result.linked_files, 1)
            self.assertEqual(result.bytes_saved, len(payload))
            self.assertEqual(first.read_bytes(), payload)
            self.assertEqual(first.stat().st_ino, second.stat().st_ino)

    def test_rejects_an_index_digest_that_does_not_match_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "media"
            media.mkdir()
            for name in ("first.bin", "second.bin"):
                (media / name).write_bytes(b"actual")
            index = root / "media-index.json"
            index.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [
                            {
                                "url": f"/media/{name}",
                                "byteSize": 6,
                                "sha256": "0" * 64,
                            }
                            for name in ("first.bin", "second.bin")
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(MediaDedupeError, "digest mismatch"):
                deduplicate_indexed_media(media, index)
            self.assertNotEqual(
                os.stat(media / "first.bin").st_ino,
                os.stat(media / "second.bin").st_ino,
            )


if __name__ == "__main__":
    unittest.main()
