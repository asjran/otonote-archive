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
from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    JobStatus,
    Region,
    VersionVector,
)
from tools.resource_pipeline.version_probe import (  # noqa: E402
    ProbeObservation,
    VersionProbe,
)


METHOD_FIXTURE = (
    REPO_ROOT
    / "tests/fixtures/resource_pipeline/client-profile/critical-methods.json"
)


class _VersionAdapter:
    def __init__(self, vector: VersionVector):
        self._vector = vector

    def observe_version(self) -> ProbeObservation:
        return ProbeObservation(version_vector=self._vector)


class NewPackageRehearsalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.methods = [
            MethodStructure.from_mapping(value)
            for value in json.loads(METHOD_FIXTURE.read_text(encoding="utf-8"))
        ]
        self.builder = ClientProfileBuilder(
            package_name="com.example.global.fixture",
            package_signature_sha256="a" * 64,
            unity_version="6000.3.12f1",
            metadata_version=39,
            abi="arm64-v8a",
        )
        self.profile = self.builder.build(
            methods=self.methods,
            sensitive_constants={"networkPreset": "synthetic-current"},
        )

    def test_only_package_identity_changes_remain_structurally_compatible(
        self,
    ) -> None:
        candidate = replace(
            self.profile,
            package_signature_sha256="b" * 64,
        )

        report = compare_client_profiles(self.profile, candidate)

        self.assertEqual(report.classification, "compatible")
        self.assertEqual(report.affected_adapters, ())

    def test_catalog_method_change_targets_only_catalog_and_asset_adapters(
        self,
    ) -> None:
        candidate = self.builder.build(
            methods=[
                replace(method, method_name="GetRemoteHashUrlV2")
                if method.type_name == "App.GameLoop.AppCatalogHandler"
                else method
                for method in self.methods
            ],
            sensitive_constants={"networkPreset": "synthetic-current"},
        )

        report = compare_client_profiles(self.profile, candidate)

        self.assertEqual(report.classification, "review_required")
        self.assertEqual(report.affected_adapters, ("asset", "catalog"))

    def test_auth_method_change_targets_transport_and_version_probe(self) -> None:
        candidate = self.builder.build(
            methods=[
                replace(method, parameter_count=method.parameter_count + 1)
                if method.type_name == "Fwk.Server.AuthenticatedCallInvoker"
                else method
                for method in self.methods
            ],
            sensitive_constants={"networkPreset": "synthetic-current"},
        )

        report = compare_client_profiles(self.profile, candidate)

        self.assertEqual(report.classification, "review_required")
        self.assertEqual(report.affected_adapters, ("transport", "version_probe"))

    def test_minimum_client_and_remote_code_changes_use_distinct_gates(self) -> None:
        build = ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.global.fixture",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="a" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="global-staging-fixture-basic",
        )
        vector = VersionVector(
            client_version="0.9.0",
            minimum_client_version="0.9.0",
            bootstrap_revision="bootstrap-1",
            catalog_hash="catalog-1",
            master_version="master-1",
            asset_manifest_version="assets-1",
            remote_code_hash="a" * 64,
        )
        probe = VersionProbe(
            client_build=build,
            previous_release=ContentRelease.for_client_build(build, vector),
            environment_id="global-staging-fixture",
            job_id="synthetic-new-package",
        )

        package_result = probe.probe(
            _VersionAdapter(replace(vector, minimum_client_version="1.0.0"))
        )
        code_result = probe.probe(
            _VersionAdapter(replace(vector, remote_code_hash="b" * 64))
        )

        self.assertEqual(
            package_result.checkpoint.status,
            JobStatus.NEEDS_PACKAGE_REVIEW,
        )
        self.assertEqual(
            code_result.checkpoint.status,
            JobStatus.NEEDS_REMOTE_CODE_REVIEW,
        )


if __name__ == "__main__":
    unittest.main()
