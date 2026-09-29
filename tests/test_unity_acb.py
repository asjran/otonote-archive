from __future__ import annotations

import unittest
from pathlib import Path

from analysis.crypto.extract_unity_acb import (
    find_unityfs_files,
    serialized_acb_payload,
)


class UnityAcbTest(unittest.TestCase):
    def test_extracts_cri_serialized_bytes_payload(self) -> None:
        payload = b"@UTF" + b"\x00" * 8 + b"AFS2" + b"\x00" * 8
        tree = {
            "references": {
                "RefIds": [
                    {
                        "type": {"class": "CriSerializedBytesAssetImpl"},
                        "data": {"data": list(payload)},
                    }
                ]
            }
        }

        self.assertEqual(serialized_acb_payload(tree), payload)

    def test_rejects_serialized_bytes_without_acb_markers(self) -> None:
        tree = {
            "references": {
                "RefIds": [
                    {
                        "type": {"class": "CriSerializedBytesAssetImpl"},
                        "data": {"data": [1, 2, 3]},
                    }
                ]
            }
        }

        self.assertIsNone(serialized_acb_payload(tree))

    def test_finds_extensionless_unityfs_files_recursively(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            extensionless = root / "a" / "hash" / "__data"
            extensionless.parent.mkdir(parents=True)
            extensionless.write_bytes(b"UnityFS\x00payload")
            (root / "not-a-bundle").write_bytes(b"@UTFpayload")

            self.assertEqual(find_unityfs_files(root), [extensionless])


if __name__ == "__main__":
    unittest.main()
