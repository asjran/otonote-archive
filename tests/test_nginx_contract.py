from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_TEMPLATE = REPO_ROOT / "deploy/nginx.conf.template"


class NginxContractTest(unittest.TestCase):
    def test_access_log_exposes_capacity_rejection_without_sensitive_fields(self) -> None:
        source = NGINX_TEMPLATE.read_text(encoding="utf-8")
        access_format = source[: source.index("limit_conn_zone")]
        self.assertIn('"limit_conn_status":"$limit_conn_status"', access_format)
        self.assertIn('"limit_req_status":"$limit_req_status"', access_format)
        self.assertNotIn("$http_cookie", access_format)
        self.assertNotIn("$http_authorization", access_format)
        self.assertNotIn("$request_body", access_format)
        self.assertNotIn("$request_uri", access_format)

    def test_hashed_media_is_immutable_and_media_parallelism_supports_auto(self) -> None:
        source = NGINX_TEMPLATE.read_text(encoding="utf-8")
        marker = 'location ~* "^/(?:media|(?:jp|global)'
        start = source.index(marker)
        end = source.index("\n    }", start)
        immutable_media = source[start:end]
        self.assertIn(
            "moc3|mp3|m4a|aac|flac|wav|ogg|mp4|webm|mov",
            immutable_media,
        )
        self.assertIn(
            'Cache-Control "public, max-age=31536000, immutable";',
            immutable_media,
        )
        self.assertIn("limit_conn ournotes_media_per_ip 8;", source)
        self.assertIn("limit_conn ournotes_media_global 24;", source)
        self.assertNotIn("limit_conn ournotes_media_per_ip 2;", source)


class NginxQueryDisabledContractTest(unittest.TestCase):
    """The failed production capacity gate keeps Query disabled.

    Static releases must preserve public 404s for both Query and internal
    adapter paths until a separately approved capacity pass changes this
    deployment-owned template.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = NGINX_TEMPLATE.read_text(encoding="utf-8")

    def test_api_v1_is_rejected_while_query_is_disabled(self) -> None:
        self.assertRegex(
            self.source,
            re.compile(
                r"location\s+\^~\s+/api/v1/\s*\{[^}]*return\s+404;\s*\}",
                re.DOTALL,
            ),
        )
        self.assertNotIn("proxy_pass http://127.0.0.1:8090;", self.source)

    def test_internal_path_is_rejected_at_the_edge(self) -> None:
        # ``/internal/`` MUST return 404 even if the request somehow
        # reaches Nginx; the loopback adapter is the only legitimate
        # caller.
        self.assertRegex(
            self.source,
            re.compile(
                r"location\s+\^~\s+/internal/\s*\{[^}]*return\s+404;\s*\}",
                re.DOTALL,
            ),
        )

    def test_request_body_size_is_capped(self) -> None:
        # 64 KiB cap matches the documented body budget.
        self.assertIn("client_max_body_size 64k;", self.source)

    def test_no_wildcard_cors_header(self) -> None:
        # ``Access-Control-Allow-Origin: *`` is forbidden on the
        # cross-origin API surface; same-origin only.
        self.assertNotIn("Access-Control-Allow-Origin: *", self.source)
        self.assertNotIn("add_header Access-Control-Allow-Origin \"*\"", self.source)

    def test_api_routes_are_first_in_match_order(self) -> None:
        # The API rejection MUST be evaluated before any generic static-file
        # catch-all so a future ``/api/v1/index.html`` does not shadow
        # the boundary. Compare against the https server's catch-all, not
        # the http redirect that appears first in the file.
        api_index = self.source.index("location ^~ /api/v1/")
        https_catchall = self.source.index("location / {", api_index)
        self.assertLess(api_index, https_catchall)


if __name__ == "__main__":
    unittest.main()
