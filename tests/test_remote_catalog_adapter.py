from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.catalog_adapter import (  # noqa: E402
    CatalogAdapter,
    UnsupportedCatalogVersion,
    catalog_snapshot_to_dict,
)


FIXTURE = REPO_ROOT / "tests/fixtures/resource_pipeline/catalog/minimal-catalog.json"


class CatalogAdapterTest(unittest.TestCase):
    def test_normalizes_graph_deduplicates_locations_and_preserves_unknowns(self) -> None:
        snapshot = CatalogAdapter().parse(FIXTURE)

        self.assertEqual(snapshot.catalog_hash, "catalog-fixture-v1")
        self.assertEqual(len(snapshot.locations), 3)
        main = snapshot.location_for_key("main")
        self.assertEqual(main.dependencies, ("dependency",))
        self.assertEqual(main.labels, ("event-1", "featured"))
        self.assertIn("main-alias", main.keys)
        self.assertEqual(main.unknown_fields["futureField"], {"preserved": True})
        self.assertEqual(snapshot.unknown_fields["futureCatalogField"], "kept")
        self.assertTrue(any("duplicate" in warning for warning in snapshot.warnings))
        self.assertTrue(any("unknown provider" in warning for warning in snapshot.warnings))
        projection = catalog_snapshot_to_dict(snapshot)
        self.assertEqual(projection["locations"][0]["internalId"], snapshot.locations[0].internal_id)
        self.assertIn("unknownFields", projection["locations"][1])

    def test_binary_header_rejects_unknown_catalog_version(self) -> None:
        data = (0x0DE38942).to_bytes(4, "little") + (99).to_bytes(4, "little")
        with self.assertRaises(UnsupportedCatalogVersion):
            CatalogAdapter().parse_bytes(data, source_name="future.bin")

    def test_protocol_pending_binary_catalog_is_parsed_from_encoded_graph(self) -> None:
        catalog = REPO_ROOT / "phone_dump/device_external/files/RemoteCatalog/catalog_main.bin"
        if not catalog.is_file():
            self.skipTest("current staging catalog is not present")

        snapshot = CatalogAdapter().parse(catalog)

        self.assertGreater(len(snapshot.locations), 100)
        self.assertTrue(any(location.dependencies for location in snapshot.locations))
        self.assertTrue(any(location.expected_size for location in snapshot.locations))
        self.assertTrue(
            any("label kind is not encoded" in warning for warning in snapshot.warnings)
        )


if __name__ == "__main__":
    unittest.main()
