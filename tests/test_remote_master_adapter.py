from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.master_adapter import (  # noqa: E402
    MasterAdapter,
    MasterAdapterError,
)


FIXTURE = REPO_ROOT / "tests/fixtures/resource_pipeline/master/minimal-manifest.json"


def _copy_decryptor(source: Path, destination: Path, **_: object) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {"payload_encoding": "test-json"}


class MasterAdapterTest(unittest.TestCase):
    def test_acquires_all_tables_atomically_with_hash_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "MasterAlpha.bin").write_text('[{"id": 1}]', encoding="utf-8")
            (source / "MasterDownload.bin").write_text(
                '[{"label": "event-1"}]', encoding="utf-8"
            )

            snapshot = MasterAdapter(decryptor=_copy_decryptor).acquire(
                FIXTURE,
                source_root=source,
                output_root=root / "output",
                crypto_material={"salt": b"s", "key": b"k", "iv": b"i"},
            )

            self.assertEqual(snapshot.version, "master-fixture-v1")
            self.assertEqual(len(snapshot.tables), 2)
            alpha = snapshot.table("MasterAlpha")
            self.assertEqual(
                alpha.encrypted_sha256,
                hashlib.sha256((source / "MasterAlpha.bin").read_bytes()).hexdigest(),
            )
            self.assertEqual(len(alpha.decrypted_sha256), 64)
            self.assertEqual(len(alpha.projected_sha256), 64)
            self.assertEqual(snapshot.catalog_evidence["MasterDownload"], ("event-1", "shared"))
            self.assertTrue(snapshot.output_dir.is_dir())

    def test_one_table_failure_rejects_partial_master(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "MasterAlpha.bin").write_text('[{"id": 1}]', encoding="utf-8")

            with self.assertRaises(MasterAdapterError):
                MasterAdapter(decryptor=_copy_decryptor).acquire(
                    FIXTURE,
                    source_root=source,
                    output_root=root / "output",
                    crypto_material={"salt": b"s", "key": b"k", "iv": b"i"},
                )

            self.assertFalse((root / "output/master-fixture-v1").exists())
            self.assertEqual(list((root / "output").glob("*.partial-*")), [])

    def test_invalid_decrypted_json_rejects_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            for name in ("MasterAlpha.bin", "MasterDownload.bin"):
                (source / name).write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(MasterAdapterError, "MasterAlpha"):
                MasterAdapter(decryptor=_copy_decryptor).acquire(
                    FIXTURE,
                    source_root=source,
                    output_root=root / "output",
                    crypto_material={"salt": b"s", "key": b"k", "iv": b"i"},
                )


if __name__ == "__main__":
    unittest.main()
