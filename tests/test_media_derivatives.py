from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.media_derivatives import (
    MediaDerivativeError,
    build_media_index,
    validate_media_index,
)


class MediaDerivativesTest(unittest.TestCase):
    def test_builds_three_tier_records_without_original_fallback(self) -> None:
        catalog = {
            "release": {"id": "release-1"},
            "assets": [
                {
                    "id": "asset-1",
                    "kind": "card",
                    "width": 1000,
                    "height": 800,
                    "sha256": "source-sha",
                    "thumbnailUrl": "/media/thumbnails/asset-1.webp",
                    "previewUrl": "/media/previews/asset-1.webp",
                    "originalUrl": "/media/originals/asset-1.png",
                    "downloadPolicy": "preview_and_download",
                    "publicPolicy": "public",
                }
            ],
            "musicTracks": [],
        }
        derivatives = {
            "asset-1": [
                {
                    "url": "/media/responsive/asset-1-640.webp",
                    "width": 640,
                    "height": 512,
                    "byteSize": 100,
                    "sha256": "derived-sha",
                    "mimeType": "image/webp",
                }
            ]
        }

        index = build_media_index(
            catalog,
            {"voices": [], "talks": [], "liveDialogues": []},
            {"items": []},
            {"models": []},
            derivatives,
            {},
            {},
        )

        record = index["records"][0]
        self.assertEqual(record["tiers"]["list"]["state"], "available")
        self.assertEqual(record["tiers"]["webPreview"]["state"], "available")
        self.assertEqual(record["tiers"]["original"]["state"], "available")
        self.assertNotEqual(
            record["tiers"]["webPreview"]["variants"][0]["url"],
            record["tiers"]["original"]["url"],
        )
        validate_media_index(index)

    def test_rejects_preview_that_falls_back_to_original(self) -> None:
        index = {
            "contentReleaseId": "release-1",
            "records": [
                {
                    "id": "asset-1",
                    "kind": "image",
                    "tiers": {
                        "list": {"state": "available", "url": "/list.webp"},
                        "webPreview": {
                            "state": "available",
                            "variants": [{"url": "/original.png"}],
                        },
                        "original": {"state": "available", "url": "/original.png"},
                    },
                }
            ],
        }

        with self.assertRaisesRegex(MediaDerivativeError, "original fallback"):
            validate_media_index(index)

    def test_accepts_explicit_missing_live2d_poster(self) -> None:
        index = build_media_index(
            {"release": {"id": "release-1"}, "assets": [], "musicTracks": []},
            {"voices": [], "talks": [], "liveDialogues": []},
            {"items": []},
            {
                "models": [
                    {
                        "modelId": "model-1",
                        "state": "available",
                        "modelUrl": "/media/live2d/model-1/model.json",
                    }
                ]
            },
            {},
            {},
            {},
        )

        record = index["records"][0]
        self.assertEqual(record["tiers"]["poster"]["state"], "source_missing")
        self.assertEqual(record["tiers"]["webPreview"]["activation"], "explicit")
        validate_media_index(index)


if __name__ == "__main__":
    unittest.main()
