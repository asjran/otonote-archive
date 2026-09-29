from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.models import (  # noqa: E402
    Channel,
    ClientBuild,
    ContentRelease,
    JobStatus,
    Region,
    VersionVector,
)
from tools.resource_pipeline.secrets import SecretUnavailable  # noqa: E402
from tools.resource_pipeline.version_probe import (  # noqa: E402
    ProbeObservation,
    VersionProbe,
)


FIXTURES = REPO_ROOT / "tests/fixtures/resource_pipeline/version-probe"


def _vector(name: str) -> VersionVector:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return VersionVector(
        client_version=value["clientVersion"],
        minimum_client_version=value["minimumClientVersion"],
        bootstrap_revision=value["bootstrapRevision"],
        catalog_hash=value["catalogHash"],
        master_version=value["masterVersion"],
        asset_manifest_version=value["assetManifestVersion"],
        remote_code_hash=value["remoteCodeHash"],
    )


class _Adapter:
    def __init__(self, observation: ProbeObservation):
        self._observation = observation

    def observe_version(self) -> ProbeObservation:
        return self._observation


class _UnavailableAuthAdapter:
    def observe_version(self) -> ProbeObservation:
        raise SecretUnavailable("example-basic", "expired")


class VersionProbeTest(unittest.TestCase):
    def _build(self) -> ClientBuild:
        return ClientBuild(
            region=Region.GLOBAL,
            channel=Channel.STAGING,
            platform="android",
            package_name="com.example.staging",
            version_name="0.9.0",
            version_code=8135,
            package_sha256="a" * 64,
            unity_version="6000.3.12f1",
            client_generation="unity6000-il2cpp39-v1",
            auth_profile_ref="example-basic",
        )

    def test_unchanged_or_http_304_does_not_create_a_release(self) -> None:
        build = self._build()
        previous = ContentRelease.for_client_build(build, _vector("unchanged.json"))
        probe = VersionProbe(
            client_build=build,
            previous_release=previous,
            environment_id="global-staging",
            job_id="probe-1",
        )

        unchanged = probe.probe(
            _Adapter(ProbeObservation(version_vector=_vector("unchanged.json")))
        )
        not_modified = probe.probe(
            _Adapter(ProbeObservation(version_vector=None, not_modified=True))
        )

        self.assertEqual(unchanged.changes, ("unchanged",))
        self.assertIsNone(unchanged.candidate_release)
        self.assertEqual(not_modified.changes, ("unchanged",))
        self.assertIsNone(not_modified.candidate_release)

    def test_preserves_all_simultaneous_content_changes(self) -> None:
        build = self._build()
        previous = ContentRelease.for_client_build(build, _vector("unchanged.json"))
        result = VersionProbe(
            client_build=build,
            previous_release=previous,
            environment_id="global-staging",
            job_id="probe-2",
        ).probe(
            _Adapter(ProbeObservation(version_vector=_vector("multi-change.json")))
        )

        self.assertEqual(
            result.changes,
            (
                "master_changed",
                "catalog_changed",
                "assets_changed",
                "bootstrap_changed",
            ),
        )
        self.assertIsNotNone(result.candidate_release)
        self.assertIsNone(result.checkpoint)

    def test_sensitive_changes_and_auth_failures_enter_manual_gates(self) -> None:
        build = self._build()
        base_vector = _vector("unchanged.json")
        previous = ContentRelease.for_client_build(build, base_vector)
        probe = VersionProbe(
            client_build=build,
            previous_release=previous,
            environment_id="global-staging",
            job_id="probe-gated",
        )

        package_gate = probe.probe(
            _Adapter(
                ProbeObservation(
                    version_vector=replace(
                        base_vector,
                        minimum_client_version="1.0.0",
                    )
                )
            )
        )
        code_gate = probe.probe(
            _Adapter(
                ProbeObservation(
                    version_vector=replace(
                        base_vector,
                        remote_code_hash="b" * 64,
                    )
                )
            )
        )
        auth_gate = probe.probe(_UnavailableAuthAdapter())

        self.assertEqual(
            package_gate.checkpoint.status,
            JobStatus.NEEDS_PACKAGE_REVIEW,
        )
        self.assertEqual(
            code_gate.checkpoint.status,
            JobStatus.NEEDS_REMOTE_CODE_REVIEW,
        )
        self.assertEqual(
            auth_gate.checkpoint.status,
            JobStatus.NEEDS_AUTH_MATERIAL,
        )
        serialized = repr((package_gate, code_gate, auth_gate))
        self.assertNotIn("example-basic", serialized)
        self.assertNotIn("test-password", serialized)


if __name__ == "__main__":
    unittest.main()
