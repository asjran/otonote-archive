"""Actual HTTP byte ranges used by audio seeking in the isolated preview."""
import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from tools.preview_independent_site import handler


class PreviewRangeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'code-release.json').write_text('{"codeId":"test"}')
        (root / 'music.m4a').write_bytes(b'0123456789')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(root, root))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, value=None, method='GET', extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            headers = {'Range': value} if value is not None else {}
            headers.update(extra or {})
            connection.request(method, '/content/music.m4a', headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_closed_open_and_suffix_ranges(self):
        for value, expected, content_range in [
            ('bytes=2-4', b'234', 'bytes 2-4/10'),
            ('bytes=7-', b'789', 'bytes 7-9/10'),
            ('bytes=-3', b'789', 'bytes 7-9/10'),
            ('bytes=8-99', b'89', 'bytes 8-9/10'),
        ]:
            with self.subTest(value=value):
                status, headers, body = self.request(value)
                self.assertEqual((status, body), (206, expected))
                self.assertEqual(headers['Content-Range'], content_range)
                self.assertEqual(int(headers['Content-Length']), len(body))
                self.assertEqual(headers['Accept-Ranges'], 'bytes')
        status, headers, body = self.request('bytes=2-4', 'HEAD')
        self.assertEqual((status, headers['Content-Length'], body), (206, '3', b''))

    def test_unsatisfiable_ranges_and_full_fallback(self):
        for value in ('bytes=10-', 'bytes=5-2', 'bytes=-0'):
            status, headers, body = self.request(value)
            self.assertEqual((status, headers['Content-Range'], body), (416, 'bytes */10', b''))
        for value in (None, 'bytes=0-1,4-5', 'bytes=abc', 'items=1-2'):
            status, headers, body = self.request(value)
            self.assertEqual((status, body), (200, b'0123456789'))
        self.assertEqual(self.request('bytes=1-2', extra={'If-Range': 'stale'})[0], 200)
