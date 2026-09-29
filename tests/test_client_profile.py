from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.client_profile import (  # noqa: E402
    ClientProfileBuilder,
    MethodStructure,
    compare_client_profiles,
)


FIXTURE = (
    REPO_ROOT
    / "tests/fixtures/resource_pipeline/client-profile/critical-methods.json"
)


class ClientProfileTest(unittest.TestCase):
    def _methods(self) -> list[MethodStructure]:
        return [
            MethodStructure.from_mapping(value)
            for value in json.loads(FIXTURE.read_text(encoding="utf-8"))
        ]

    def test_same_structure_has_stable_fingerprint_despite_native_addresses(
        self,
    ) -> None:
        builder = ClientProfileBuilder(
            package_name="com.example.staging",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        original = builder.build(
            methods=self._methods(),
            sensitive_constants={"serverRoot": "https://secret.example.test"},
        )
        relocated_methods = [
            method.with_native_address(
                None if method.native_address is None else method.native_address + 4096
            )
            for method in self._methods()
        ]
        relocated = builder.build(
            methods=relocated_methods,
            sensitive_constants={"serverRoot": "https://secret.example.test"},
        )

        self.assertEqual(original.structure_fingerprint, relocated.structure_fingerprint)
        self.assertEqual(original.to_public_dict(), relocated.to_public_dict())
        self.assertNotIn(
            "https://secret.example.test",
            json.dumps(original.to_public_dict()),
        )

    def test_relocated_native_methods_remain_compatible(self) -> None:
        builder = ClientProfileBuilder(
            package_name="com.example.staging",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        previous = builder.build(methods=self._methods(), sensitive_constants={})
        relocated = builder.build(
            methods=[
                method.with_native_address(
                    None
                    if method.native_address is None
                    else method.native_address + 8192
                )
                for method in self._methods()
            ],
            sensitive_constants={},
        )

        report = compare_client_profiles(previous, relocated)

        self.assertEqual(report.classification, "compatible")
        self.assertEqual(report.affected_adapters, ())

    def test_missing_network_node_requires_transport_and_probe_review(self) -> None:
        builder = ClientProfileBuilder(
            package_name="com.example.staging",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        previous = builder.build(methods=self._methods(), sensitive_constants={})
        candidate = builder.build(
            methods=[
                method
                for method in self._methods()
                if method.type_name != "App.Config.NetworkConfig"
            ],
            sensitive_constants={},
        )

        report = compare_client_profiles(previous, candidate)

        self.assertEqual(report.classification, "review_required")
        self.assertEqual(report.affected_adapters, ("transport", "version_probe"))
        self.assertIn("App.Config.NetworkConfig", " ".join(report.changes))

    def test_changed_metadata_format_is_unsupported(self) -> None:
        builder = ClientProfileBuilder(
            package_name="com.example.staging",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        previous = builder.build(methods=self._methods(), sensitive_constants={})
        candidate = replace(previous, metadata_version=40)

        report = compare_client_profiles(previous, candidate)

        self.assertEqual(report.classification, "unsupported")
        self.assertIn("metadata", " ".join(report.changes).lower())

    def test_protocol_service_summary_is_public_and_versioned(self) -> None:
        builder = ClientProfileBuilder(
            package_name="com.example.staging",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        previous = builder.build(
            methods=self._methods(),
            sensitive_constants={},
            protocol_services={"ContentService": ("GetVersion", "GetMaster")},
        )
        candidate = builder.build(
            methods=self._methods(),
            sensitive_constants={},
            protocol_services={"ContentService": ("GetVersionV2", "GetMaster")},
        )

        self.assertEqual(
            previous.to_public_dict()["protocolServices"]["ContentService"],
            ["GetMaster", "GetVersion"],
        )
        report = compare_client_profiles(previous, candidate)
        self.assertEqual(report.classification, "review_required")
        self.assertEqual(report.affected_adapters, ("transport", "version_probe"))


if __name__ == "__main__":
    unittest.main()
