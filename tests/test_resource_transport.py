from __future__ import annotations

import sys
import io
import json
import urllib.error
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.resource_pipeline.secrets import (  # noqa: E402
    EnvironmentSecretProvider,
    SecretUnavailable,
)
from tools.resource_pipeline.transport import (  # noqa: E402
    HttpRequest,
    HttpTransport,
    TransportError,
)


class EnvironmentSecretProviderTest(unittest.TestCase):
    def test_resolves_basic_auth_by_reference_without_exposing_values(self) -> None:
        provider = EnvironmentSecretProvider(
            environ={
                "OURNOTES_SECRET_GLOBAL_STAGING_FIXTURE_BASIC_USER": "test-user",
                "OURNOTES_SECRET_GLOBAL_STAGING_FIXTURE_BASIC_PASS": "test-password",
            },
            now=lambda: datetime(2026, 7, 18, tzinfo=timezone.utc),
        )

        credentials = provider.resolve_basic("global-staging-fixture-basic")

        self.assertEqual(credentials.username, "test-user")
        self.assertEqual(credentials.password, "test-password")
        self.assertEqual(credentials.auth_profile_ref, "global-staging-fixture-basic")
        self.assertNotIn("test-user", repr(credentials))
        self.assertNotIn("test-password", repr(credentials))

        with self.assertRaisesRegex(SecretUnavailable, "missing-basic") as raised:
            provider.resolve_basic("missing-basic")
        self.assertNotIn("test-password", str(raised.exception))

    def test_rejects_expired_auth_material(self) -> None:
        provider = EnvironmentSecretProvider(
            environ={
                "OURNOTES_SECRET_GLOBAL_STAGING_FIXTURE_BASIC_USER": "test-user",
                "OURNOTES_SECRET_GLOBAL_STAGING_FIXTURE_BASIC_PASS": "test-password",
                "OURNOTES_SECRET_GLOBAL_STAGING_FIXTURE_BASIC_EXPIRES_AT": (
                    "2026-07-17T00:00:00Z"
                ),
            },
            now=lambda: datetime(2026, 7, 18, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(SecretUnavailable, "expired"):
            provider.resolve_basic("global-staging-fixture-basic")


class _Response:
    def __init__(self, body: bytes, *, status: int = 200):
        self.status = status
        self.headers = {"ETag": '"catalog-v1"'}
        self._stream = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class HttpTransportTest(unittest.TestCase):
    def test_allows_configured_host_and_redacts_sensitive_request_data(self) -> None:
        captured = []

        def sender(request: object, timeout: float) -> _Response:
            captured.append((request, timeout))
            return _Response(b"catalog-version")

        transport = HttpTransport(
            allowed_hosts=("assets.example.test",),
            connect_timeout_seconds=3,
            read_timeout_seconds=7,
            max_response_bytes=1024,
            sender=sender,
        )
        request = HttpRequest(
            method="GET",
            url=(
                "https://assets.example.test/catalog?token=top-secret"
                "&platform=android"
            ),
            headers={
                "Authorization": "Basic top-secret",
                "Cookie": "session=top-secret",
                "If-None-Match": '"catalog-v0"',
                "Range": "bytes=0-99",
            },
        )

        response = transport.request(request)
        summary = transport.safe_request_summary(request)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"catalog-version")
        self.assertEqual(response.headers["etag"], '"catalog-v1"')
        self.assertTrue(transport.tls_verification_enabled)
        self.assertEqual(len(captured), 1)
        self.assertNotIn("top-secret", json.dumps(summary))
        self.assertIn("REDACTED", json.dumps(summary))

        with self.assertRaisesRegex(TransportError, "not allowed") as raised:
            transport.request(
                HttpRequest(
                    method="GET",
                    url="https://evil.example.test/?token=top-secret",
                )
            )
        self.assertNotIn("top-secret", str(raised.exception))

    def test_streams_with_a_size_limit_and_blocks_cross_host_redirects(self) -> None:
        transport = HttpTransport(
            allowed_hosts=("assets.example.test",),
            connect_timeout_seconds=3,
            read_timeout_seconds=7,
            max_response_bytes=4,
            sender=lambda request, timeout: _Response(b"12345"),
        )
        with self.assertRaisesRegex(TransportError, "size limit"):
            transport.request(
                HttpRequest(method="GET", url="https://assets.example.test/large")
            )

        output = io.BytesIO()
        streaming = HttpTransport(
            allowed_hosts=("assets.example.test",),
            connect_timeout_seconds=3,
            read_timeout_seconds=7,
            max_response_bytes=10,
            sender=lambda request, timeout: _Response(b"streamed"),
        )
        receipt = streaming.download(
            HttpRequest(method="GET", url="https://assets.example.test/bundle"),
            output,
        )
        self.assertEqual(receipt.byte_size, 8)
        self.assertEqual(output.getvalue(), b"streamed")

        def redirect_failure(request: object, timeout: float) -> _Response:
            raise urllib.error.URLError("redirect host is not allowed")

        redirecting = HttpTransport(
            allowed_hosts=("assets.example.test",),
            connect_timeout_seconds=3,
            read_timeout_seconds=3,
            max_response_bytes=1024,
            sender=redirect_failure,
        )
        with self.assertRaisesRegex(TransportError, "request failed") as raised:
            redirecting.request(
                HttpRequest(
                    method="GET",
                    url="https://assets.example.test/?token=top-secret",
                )
            )
        self.assertNotIn("top-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
