"""T3 tests for the FastAPI HTTP adapter.

These tests exercise the public GET paths under ``/api/v1/`` plus the
loopback health checks via FastAPI ``TestClient``. They cover the three
documented HTTP statuses (200 valid, 400 invalid params, 503 integrity
failure), the disabled Swagger/ReDoc routes, the short ``Cache-Control``
header, and the sanitized error responses (no absolute paths, no
tracebacks).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as backend_app  # noqa: E402
from backend.config import (  # noqa: E402
    EnabledEnvironment,
    QueryServiceConfig,
)
from backend.contracts import (  # noqa: E402
    Channel,
    Dataset,
    Locale,
    Region,
)
from backend.query import DatasetQueryModule  # noqa: E402
from tools.resource_pipeline.models import (  # noqa: E402
    Channel as ModelChannel,
    ClientBuild,
    ContentRelease,
    Region as ModelRegion,
    VersionVector,
)
from tools.resource_pipeline.query_projection import (  # noqa: E402
    build_query_projections,
    publish_query_projections,
)
from tools.resource_pipeline.release_repository import (  # noqa: E402
    ReleaseRepository,
)


def _release(catalog_hash: str, region: ModelRegion, channel: ModelChannel) -> ContentRelease:
    build = ClientBuild(
        region=region,
        channel=channel,
        platform="android",
        package_name="com.example.fixture",
        version_name="1.0.0",
        version_code=1,
        package_sha256="a" * 64,
        unity_version="6000.3.12f1",
        client_generation="fixture-v1",
        auth_profile_ref="fixture-auth",
    )
    return ContentRelease.for_client_build(
        build,
        VersionVector(
            client_version="1.0.0+1",
            minimum_client_version=None,
            bootstrap_revision="bootstrap-1",
            catalog_hash=catalog_hash,
            master_version="master-1",
            asset_manifest_version=None,
            remote_code_hash=None,
        ),
    )


def _publish_release(
    repository: ReleaseRepository,
    release: ContentRelease,
    *,
    event_items: list[dict] | None = None,
) -> None:
    payloads = build_query_projections(Path("/nonexistent-master"), release.id)
    if event_items is not None:
        payloads[Dataset.EVENTS] = {
            "dataset": "events",
            "datasetSchemaVersion": 1,
            "availability": "available",
            "freshness": "fresh",
            "provenance": "configured",
            "warnings": [],
            "items": event_items,
        }
    repository.create_candidate(release, {"objects": []})
    publish_query_projections(repository, release, payloads)
    repository.publish_candidate(release.region, release.channel, release.id)


def _make_config(root: Path) -> QueryServiceConfig:
    return QueryServiceConfig(
        data_root=root / "content",
        host="127.0.0.1",
        port=8090,
        enabled_environments=(
            EnabledEnvironment(region=Region.GLOBAL, channel=Channel.PRODUCTION),
        ),
        freshness_seconds=300,
        cache_control_max_age=30,
    )


def _build_app(config: QueryServiceConfig):
    return backend_app.create_app(config)


class HealthLiveTest(unittest.TestCase):
    def test_live_returns_200_without_filesystem(self) -> None:
        # live MUST NOT touch the filesystem so it can answer immediately
        # even when the release tree is missing.
        with tempfile.TemporaryDirectory() as temporary:
            config = QueryServiceConfig(
                data_root=Path(temporary) / "missing",
                host="127.0.0.1",
                port=8090,
                enabled_environments=(
                    EnabledEnvironment(region=Region.GLOBAL, channel=Channel.PRODUCTION),
                ),
                freshness_seconds=300,
                cache_control_max_age=30,
            )
            app = _build_app(config)
            client = TestClient(app)

            response = client.get("/api/v1/health/live")

            response = client.get("/api/v1/health/live")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "live"})


class ProductionFactoryTest(unittest.TestCase):
    def test_factory_loads_environment_and_initializes_identity_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {
                "OURNOTES_DATA_ROOT": str(root),
                "OURNOTES_QUERY_ENABLED_ENVIRONMENTS": "global-production",
            }
            with patch.dict(os.environ, environment, clear=True):
                app = backend_app.create_app_from_environment()

            client = TestClient(app)
            self.assertEqual(
                client.get("/api/v1/health/live").json(), {"status": "live"}
            )
            self.assertTrue((root / "identity" / "identity.sqlite3").is_file())


class HealthReadyTest(unittest.TestCase):
    def test_ready_returns_200_when_at_least_one_env_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("ready-ok", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            config = _make_config(root)
            app = _build_app(config)
            client = TestClient(app)

            response = client.get("/api/v1/health/ready")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ready")
            environments = payload["environments"]
            self.assertEqual(len(environments), 1)
            self.assertEqual(environments[0]["region"], "global")
            self.assertEqual(environments[0]["channel"], "production")
            self.assertTrue(environments[0]["contentReleaseId"])

    def test_ready_returns_503_when_no_env_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _make_config(Path(temporary))
            app = _build_app(config)
            client = TestClient(app)

            response = client.get("/api/v1/health/ready")

            self.assertEqual(response.status_code, 503)
            payload = response.json()
            self.assertEqual(payload["status"], "not_ready")
            self.assertEqual(payload["environments"], [])


class DatasetQueryRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        root = Path(self._tempdir.name)
        repository = ReleaseRepository(root / "content")
        release = _release("route-ok", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
        _publish_release(
            repository,
            release,
            event_items=[
                {
                    "eventId": "event-http",
                    "localizedText": {"ja": "イベント"},
                    "startAt": "2026-08-01T00:00:00Z",
                    "endAt": "2026-08-15T23:59:59Z",
                    "state": "active",
                    "rankingAvailable": False,
                    "sourceRef": "0" * 64,
                }
            ],
        )
        self.config = _make_config(root)
        self.client = TestClient(_build_app(self.config))

    def _query(self, path: str, params: dict[str, str] | None = None):
        from urllib.parse import urlencode
        url = f"/api/v1{path}"
        if params:
            query = urlencode(params)
            url = f"{url}?{query}"
        return self.client.get(url)

    def test_events_returns_200_envelope(self) -> None:
        response = self._query(
            "/events",
            {"region": "global", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["dataset"], "events")
        self.assertEqual(payload["availability"], "available")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["eventId"], "event-http")

    def test_rankings_returns_no_observation(self) -> None:
        response = self._query(
            "/rankings",
            {"region": "global", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["availability"], "unavailable")
        self.assertEqual(payload["freshness"], "unknown")
        self.assertEqual(payload["provenance"], "unknown")
        codes = [warning["code"] for warning in payload["warnings"]]
        self.assertIn("no_observation", codes)

    def test_gacha_pools_returns_unavailable_with_source_mapping_warning(self) -> None:
        response = self._query(
            "/gacha-pools",
            {"region": "global", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["availability"], "unavailable")
        codes = [warning["code"] for warning in payload["warnings"]]
        self.assertIn("source_mapping_unverified", codes)

    def test_shops_returns_unavailable_with_source_mapping_warning(self) -> None:
        response = self._query(
            "/shops",
            {"region": "global", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["availability"], "unavailable")
        codes = [warning["code"] for warning in payload["warnings"]]
        self.assertIn("source_mapping_unverified", codes)

    def test_cache_control_header_is_set(self) -> None:
        response = self._query(
            "/events",
            {"region": "global", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "max-age=30, public")

    def test_invalid_region_returns_400(self) -> None:
        response = self._query(
            "/events",
            {"region": "cn", "channel": "production", "locale": "ja"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("region", payload.get("detail", {}).get("error", ""))
        self.assertNotIn("/srv/", response.text)
        self.assertNotIn("Traceback", response.text)

    def test_invalid_locale_returns_400(self) -> None:
        response = self._query(
            "/events",
            {"region": "global", "channel": "production", "locale": "de"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("locale", payload.get("detail", {}).get("error", ""))

    def test_invalid_limit_returns_400(self) -> None:
        response = self._query(
            "/events",
            {"region": "global", "channel": "production", "locale": "ja", "limit": "999"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("limit", payload.get("detail", {}).get("error", ""))

    def test_invalid_cursor_returns_400(self) -> None:
        response = self._query(
            "/events",
            {
                "region": "global",
                "channel": "production",
                "locale": "ja",
                "cursor": "###not-a-cursor###",
            },
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("cursor", payload.get("detail", {}).get("error", ""))


class IntegrityFailureRouteTest(unittest.TestCase):
    def test_manifest_tamper_returns_503_without_disk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("tamper", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            manifest_path = (
                repository.release_root
                / release.region.value
                / release.channel.value
                / release.id
                / "manifest.json"
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["contentRelease"]["id"] = "different-id"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            config = _make_config(root)
            client = TestClient(_build_app(config))

            response = client.get(
                "/api/v1/events",
                params={
                    "region": "global",
                    "channel": "production",
                    "locale": "ja",
                },
            )

            self.assertEqual(response.status_code, 503)
            body = response.json()
            self.assertNotIn(str(manifest_path), response.text)
            self.assertNotIn("Traceback", response.text)
            self.assertEqual(body["error"], "integrity_check_failed")

    def test_dataset_tamper_returns_503(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ReleaseRepository(root / "content")
            release = _release("tamper-data", ModelRegion.GLOBAL, ModelChannel.PRODUCTION)
            _publish_release(repository, release)

            dataset_path = (
                repository.release_root
                / release.region.value
                / release.channel.value
                / release.id
                / "query"
                / "events.json"
            )
            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
            payload["items"] = [{"eventId": "forged"}]
            dataset_path.write_text(json.dumps(payload), encoding="utf-8")

            config = _make_config(root)
            client = TestClient(_build_app(config))

            response = client.get(
                "/api/v1/events",
                params={
                    "region": "global",
                    "channel": "production",
                    "locale": "ja",
                },
            )

            self.assertEqual(response.status_code, 503)
            body = response.json()
            self.assertNotIn(str(dataset_path), response.text)
            self.assertEqual(body["error"], "integrity_check_failed")


class DocsDisabledTest(unittest.TestCase):
    def test_swagger_and_redoc_are_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _make_config(Path(temporary))
            app = _build_app(config)
            client = TestClient(app)

            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/redoc").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)


class QueryServiceFactoryTest(unittest.TestCase):
    def test_create_app_accepts_injected_module(self) -> None:
        # Callers (e.g. tests) can inject a pre-built module to keep the
        # app factory side-effect free.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _make_config(root)
            module = DatasetQueryModule(release_root=root / "data" / "releases")
            app = backend_app.create_app(config, module=module)
            client = TestClient(app)

            response = client.get(
                "/api/v1/events",
                params={
                    "region": "global",
                    "channel": "production",
                    "locale": "ja",
                },
            )

            self.assertIn(response.status_code, (200, 503))


if __name__ == "__main__":
    unittest.main()
