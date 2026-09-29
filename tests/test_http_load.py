from __future__ import annotations

import unittest
import urllib.error
from email.message import Message
from io import BytesIO
from unittest import mock

from tools.http_load import fetch


class HttpLoadRequestTest(unittest.TestCase):
    def test_fetch_preserves_http_error_status_and_separates_ttfb_from_total(self) -> None:
        body = b"temporarily unavailable"
        error = urllib.error.HTTPError(
            "http://fixture.invalid/error",
            503,
            "Service Unavailable",
            Message(),
            BytesIO(body),
        )
        with (
            mock.patch("tools.http_load.urllib.request.urlopen", side_effect=error),
            mock.patch(
                "tools.http_load.time.perf_counter",
                side_effect=[10.0, 10.01, 10.04],
            ),
        ):
            result = fetch("http://fixture.invalid/error", timeout=1)

        self.assertEqual(result["status"], 503)
        self.assertEqual(result["bytes"], len(body))
        self.assertLess(float(result["ttfbMs"]), float(result["totalMs"]))
        self.assertEqual(result["ttfbMs"], 10.0)
        self.assertEqual(result["totalMs"], 40.0)


if __name__ == "__main__":
    unittest.main()
