"""Bounded JP client transport; callers must supply explicitly authorized credentials.

Only resource-version RPCs and the official static host are allowed. This module
does not discover credentials, log them, access player data, or retry refusals.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
import uuid

from .global_public import ProtocolError, VERSION, allowed_url, decode_grpc, protobuf_fields, string_field, utc_now
from ..transport import HttpRequest, HttpTransport, TransportError

API_ROOT = 'https://api.bang-dream-on.jp'
CDN_ROOT = 'https://static.bang-dream-on.jp'
READ_METHODS = frozenset({
    'app.masterdata.MasterdataService/Version',
})
RESOURCE_VERSION = re.compile(r'([0-9]+(?:\.[0-9]+){1,4})/([0-9a-f]{32})')


def version_parts(value):
    match = RESOURCE_VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ProtocolError('invalid JP resource version')
    return match.groups()


def asset_directory(version):
    release, digest = version_parts(version)
    return f'{CDN_ROOT}/asset/{release}/Android/{digest}'


def asset_url(version, internal_id):
    prefix = '{Fwk.Resource.RemoteAssetDir}/'
    if not isinstance(internal_id, str) or not internal_id.startswith(prefix):
        raise ProtocolError('unexpected JP catalog resource path')
    path = internal_id[len(prefix):]
    if (not re.fullmatch(r'[A-Za-z0-9_./()\-]+', path)
            or any(part in ('', '.', '..') for part in path.split('/'))):
        raise ProtocolError('unexpected JP catalog resource path')
    return asset_directory(version) + '/' + path


def decode_catalog(body, limit=64_000_000):
    # The CDN serves gzip bytes; the installed client caches the decoded catalog.
    if body.startswith(b'\x1f\x8b'):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                body = stream.read(limit + 1)
        except (OSError, EOFError):
            raise ProtocolError('invalid JP compressed catalog') from None
    if len(body) > limit:
        raise ProtocolError('JP decoded catalog exceeds size limit')
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JpPublicClient:
    def __init__(self, client_version, authorization):
        if not VERSION.fullmatch(client_version):
            raise ProtocolError('invalid JP client version')
        if not isinstance(authorization, str) or not re.fullmatch(r'Basic [A-Za-z0-9+/]+={0,2}', authorization):
            raise ProtocolError('explicit JP client authorization is required')
        try:
            decoded = base64.b64decode(authorization[6:], validate=True)
        except ValueError:
            raise ProtocolError('invalid JP client authorization') from None
        if b':' not in decoded or any(x in decoded for x in (b'\r', b'\n', b'\x00')):
            raise ProtocolError('invalid JP client authorization')
        self.client_version = client_version
        self._authorization = authorization

    def rpc(self, method):
        if method not in READ_METHODS:
            raise ProtocolError('unsupported JP read-only RPC')
        with tempfile.TemporaryDirectory(prefix='ournotes-jp-rpc-') as temporary:
            directory = Path(temporary)
            headers, body, request = (directory/name for name in ('headers', 'body', 'request'))
            request.write_bytes(bytes(5))
            # curl receives the secret through stdin, never process arguments.
            configuration = 'header = ' + json.dumps('Authorization: ' + self._authorization) + '\n'
            command = ['curl', '--disable', '--config', '-', '--http2', '--proto', '=https',
                       '--max-time', '30', '--max-filesize', '1048576', '--silent', '--show-error',
                       '--dump-header', str(headers), '--output', str(body),
                       '-H', 'Content-Type: application/grpc', '-H', 'TE: trailers',
                       '-H', 'x-client-version: ' + self.client_version, '-H', 'x-platform: android',
                       '-H', 'x-request-id: ' + uuid.uuid4().hex,
                       '--user-agent', 'OurNotes/' + self.client_version,
                       '--data-binary', '@' + str(request), API_ROOT + '/' + method]
            completed = subprocess.run(command, input=configuration.encode(), capture_output=True, timeout=35)
            if completed.returncode:
                raise TransportError('JP read-only RPC transport failed (' + str(completed.returncode) + ')')
            return decode_grpc(headers.read_text(), body.read_bytes())

    def _transport(self, url, limit):
        allowed_url(url, ('static.bang-dream-on.jp',))
        # Never redirect authenticated requests, including HTTPS-to-HTTP on this host.
        opener = urllib.request.build_opener(_NoRedirect())
        return HttpTransport(allowed_hosts=('static.bang-dream-on.jp',),
                             connect_timeout_seconds=30, read_timeout_seconds=30,
                             max_response_bytes=limit,
                             sender=lambda request, timeout: opener.open(request, timeout=timeout))

    def _headers(self):
        return {'Authorization': self._authorization, 'User-Agent': 'OurNotes/' + self.client_version}

    def get(self, url, limit, *, method='GET'):
        if method not in {'GET', 'HEAD'}:
            raise ProtocolError('unsupported JP resource method')
        response = self._transport(url, limit).request(HttpRequest(method, url, self._headers()))
        if response.status != 200:
            raise ProtocolError('JP resource HTTP ' + str(response.status))
        return response

    def download(self, url, stream, limit):
        response = self._transport(url, limit).download(HttpRequest('GET', url, self._headers()), stream)
        if response.status != 200:
            raise ProtocolError('JP resource HTTP ' + str(response.status))
        return response

    def discover(self):
        # JP VersionResponse has only field 1; resource version arrives in a header.
        # Live access is still gated by the official API; do not fall back to a cached
        # version and label it current when this request is refused.
        headers, payload = self.rpc('app.masterdata.MasterdataService/Version')
        master = string_field(protobuf_fields(payload), 1)
        resource = headers.get('x-asset-version')
        version_parts(master)
        _, digest = version_parts(resource)
        recommended = headers.get('x-client-recommended-version')
        if recommended and recommended != self.client_version:
            raise ProtocolError('JP client version changed; a verified client intake is required')
        return {'schemaVersion': 1, 'environmentId': 'jp-production', 'region': 'jp',
                'observedAt': utc_now(), 'clientVersion': self.client_version,
                'masterVersion': master, 'resourceVersion': resource, 'catalogHash': digest,
                'apiRoot': API_ROOT, 'cdnRoot': CDN_ROOT,
                'catalogUrl': asset_directory(resource) + '/catalog_main.bin',
                'masterManifestUrl': CDN_ROOT + '/master/' + master + '/MasterManifest.json',
                'responseHeaders': headers, 'authentication': 'authorized_client_builtin'}
