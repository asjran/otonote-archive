"""JP source verification and incremental CDN acquisition.

The version RPC must succeed before a caller may treat a source as current.
``verify-capture`` validates a known capture only; it never publishes or schedules.
No player account material is read. Client credentials stay in memory.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from tools.global_remote_sync import file_hash, read_json, validate_manifest, write_json
from tools.jp_phone_inputs import JP_METADATA_SHA256
from tools.resource_pipeline.adapters.global_public import ProtocolError, utc_now
from tools.resource_pipeline.adapters.jp_public import (
    CDN_ROOT, JpPublicClient, asset_directory, asset_url, decode_catalog, version_parts,
)
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.transport import TransportError


# Verified NetworkConfig literals in the signed JP 1.0.4 client. Do not apply these
# offsets to another client, even when the requested version number is unchanged.
def client_from_metadata(path, *, authorize_builtin_credentials=False):
    if not authorize_builtin_credentials:
        raise ProtocolError('explicit authorization for JP client credentials is required')
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != JP_METADATA_SHA256:
        raise ProtocolError('unverified JP client metadata; a new intake is required')
    if struct.unpack_from('<II', data) != (0xFAB11BAF, 39):
        raise ProtocolError('unexpected JP metadata format')
    offsets = struct.unpack_from('<III', data, 8)
    strings = struct.unpack_from('<III', data, 20)
    def literal(index):
        start, end = struct.unpack_from('<II', data, offsets[0] + index * 4)
        if not 0 <= start < end <= strings[1]:
            raise ProtocolError('invalid JP client credential binding')
        return data[strings[0]+start:strings[0]+end]
    credential = base64.b64encode(literal(43395) + b':' + literal(41482)).decode('ascii')
    return JpPublicClient('1.0.4', 'Basic ' + credential)


def acquire(client, url, target, size, *, expected_sha=None, identity=None):
    """Reuse only size+digest-verified bytes bound to the same catalog identity.

    URLs include version directories which can change for identical resources;
    caller-provided catalog identity allows verified reuse across those directories.
    A corrupt cache fails closed and is never handed to a decoder.
    """
    from tools.resource_pipeline.adapters.global_public import allowed_url
    allowed_url(url, ('static.bang-dream-on.jp',))
    if type(size) is not int or not 0 < size <= 256_000_000:
        raise ProtocolError('invalid JP resource size')
    if expected_sha is not None and (len(expected_sha) != 64 or any(c not in '0123456789abcdef' for c in expected_sha)):
        raise ProtocolError('invalid JP resource digest')
    if expected_sha is None and not identity:
        raise ProtocolError('JP resource requires a catalog identity or SHA-256')
    target = Path(target)
    receipt = target.with_name(target.name + '.receipt.json')
    if target.is_symlink() or receipt.is_symlink():
        raise ProtocolError('refusing a symlink output')
    if target.exists():
        digest = file_hash(target)
        old = read_json(receipt) if receipt.exists() else {}
        valid = digest == expected_sha if expected_sha else (old.get('sha256') == digest and old.get('identity') == identity)
        if target.stat().st_size != size or not valid:
            raise ProtocolError('JP cached resource does not match its receipt')
        return {'path': str(target), 'sha256': digest, 'byteSize': size, 'reused': True}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.jp-download-', dir=target.parent) as temporary:
        part = Path(temporary)/'part'
        with part.open('wb') as stream:
            response = client.download(url, stream, size)
        if response.byte_size != size or part.stat().st_size != size:
            raise ProtocolError('JP downloaded resource size mismatch')
        digest = file_hash(part)
        if expected_sha and digest != expected_sha:
            raise ProtocolError('JP downloaded resource SHA-256 mismatch')
        # S3 single-part ETags are checked when present; Unity catalog hashes are
        # identities, not SHA-256/MD5 hashes of the encrypted wire representation.
        etag = response.headers.get('etag', '').strip('"').lower()
        if len(etag) == 32 and all(c in '0123456789abcdef' for c in etag):
            md5 = hashlib.md5()
            with part.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    md5.update(chunk)
            if md5.hexdigest() != etag:
                raise ProtocolError('JP downloaded resource ETag mismatch')
        result = {'path': str(target), 'url': url, 'byteSize': size, 'sha256': digest,
                  'identity': identity, 'etag': etag or None, 'reused': False}
        write_json(receipt, result)
        part.replace(target)
    return result


def resource_identity(location):
    if not location.expected_hash or not location.expected_size:
        raise ProtocolError('JP catalog resource is missing a hash or size')
    return {'key': location.primary_key, 'hash': location.expected_hash,
            'size': location.expected_size, 'provider': location.provider_id,
            'resourceType': location.resource_type}


def verify_capture(client, capture):
    """Read two CDN manifests and compare them to a pinned, local capture."""
    capture = Path(capture)
    resource = (capture/'RemoteCatalog/catalog_main.cached_hash').read_text().strip()
    master = read_json(capture/'Master/MasterManifest.json')['version']
    version_parts(resource); version_parts(master)
    url = asset_directory(resource) + '/catalog_main.bin'
    wire = client.get(url, 64_000_000).body
    decoded = decode_catalog(wire)
    catalog = CatalogAdapter().parse_bytes(decoded)
    if decoded != (capture/'RemoteCatalog/catalog_main.bin').read_bytes():
        raise ProtocolError('JP remote catalog differs from the selected capture')
    manifest = json.loads(client.get(CDN_ROOT+'/master/'+master+'/MasterManifest.json', 4_000_000).body)
    rows = validate_manifest(manifest, master)
    for row in rows:
        path = capture/'Master'/row['name']
        if path.stat().st_size != row['size'] or file_hash(path) != row['hash']:
            raise ProtocolError('JP Master file differs from the selected capture: '+row['name'])
    locations = [r for r in catalog.locations if r.internal_id.startswith('{Fwk.Resource.RemoteAssetDir}/')]
    for location in locations:
        asset_url(resource, location.internal_id)
        resource_identity(location)
    return {'schemaVersion': 1, 'status': 'verified_known_capture', 'region': 'jp',
            'verifiedAt': utc_now(), 'latestVersionVerified': False,
            'masterVersion': master, 'resourceVersion': resource,
            'catalogSha256': hashlib.sha256(decoded).hexdigest(),
            'catalogWireBytes': len(wire), 'catalogDecodedBytes': len(decoded),
            'masterFilesVerified': len(rows), 'remoteResources': len(locations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('probe', 'verify-capture'))
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--allow-client-builtin-credentials', action='store_true')
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        client = client_from_metadata(args.metadata, authorize_builtin_credentials=args.allow_client_builtin_credentials)
        if args.action == 'verify-capture':
            if not args.capture: parser.error('--capture is required for verify-capture')
            result = verify_capture(client, args.capture)
        else:
            result = client.discover()
    except (ProtocolError, TransportError, OSError, ValueError) as error:
        write_json(args.output, {'status': 'blocked', 'region': 'jp', 'checkedAt': utc_now(),
                                'latestVersionVerified': False, 'error': str(error)})
        print(str(error)); return 1
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
