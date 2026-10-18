"""Acquire a recommended JP client, verify it in isolation, then replace its seed."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlsplit
import zipfile

from tools.global_remote_sync import file_hash, verify_apk_signature, write_json
from tools.jp_client_profile import (ANCHOR_NAME, MAX_METADATA_BYTES, PROFILE_NAME,
    derive_binding, validate_package)
from tools.jp_client_refresh import XAPK_APKS
from tools.jp_phone_inputs import JP_APKSIG_SHA256, JP_APKSIG_URL, JP_CERTIFICATE_SHA256, JP_METADATA_SHA256
from tools.jp_remote_sync import client_from_metadata
from tools.resource_pipeline.adapters.jp_public import JpClientUpdateRequired
from tools.resource_pipeline.package_intake import build_package_set_manifest

LATEST_XAPK = 'https://d.apkpure.net/b/XAPK/com.bushiroad.sirius?version=latest'
PACKAGE_HOSTS = frozenset({'d.apkpure.net', 'data.winudf.com'})
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
SUPPORTED_UNITY = '6000.3.12f1'
SEED_FILES = ('apks', 'metadata.v39.dat', 'unity-version.txt', PROFILE_NAME, ANCHOR_NAME)


def download_file(url, target, *, hosts=PACKAGE_HOSTS, limit=MAX_ARCHIVE_BYTES):
    """Bound each redirect before requesting it; do not log signed CDN URLs."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError('JP download target already exists')
    deadline = time.monotonic() + 600
    with tempfile.TemporaryDirectory(prefix='.jp-download-', dir=target.parent) as temp:
        body, headers = Path(temp)/'body', Path(temp)/'headers'
        for _ in range(5):
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.port not in (None,443)
                    or parsed.username or parsed.password or parsed.fragment or '\\' in url
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in url) or len(url) > 8192):
                raise ValueError('untrusted JP package download URL')
            remaining = int(deadline-time.monotonic())
            if remaining <= 0:
                raise ValueError('JP package download timed out')
            command = ['curl', '--disable', '--proto', '=https', '--silent', '--show-error',
                       '--max-time', str(remaining), '--max-filesize', str(limit),
                       '--dump-header', str(headers), '--output', str(body), '--write-out', '%{http_code}',
                       '--user-agent', 'Android', url]
            try:
                result = subprocess.run(command, capture_output=True, timeout=remaining+5)
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError('JP package download transport failed') from None
            if result.returncode:
                raise ValueError('JP package download transport failed')
            status = result.stdout.decode('ascii', errors='replace').strip()
            if status in ('301','302','303','307','308'):
                locations = re.findall(r'^location:\s*([^\r\n]+)', headers.read_text(), re.I|re.M)
                if len(locations) != 1:
                    raise ValueError('invalid JP package redirect')
                url = urljoin(url, locations[0].strip())
                continue
            if status != '200' or not 0 < body.stat().st_size <= limit:
                raise ValueError('JP package download unavailable or exceeds limit')
            os.replace(body, target)
            return
        raise ValueError('too many JP package redirects')


def _member(archive, name, limit):
    matches = [i for i in archive.infolist() if i.filename == name]
    if (len(matches) != 1 or matches[0].is_dir() or not 0 < matches[0].file_size <= limit
            or stat.S_ISLNK(matches[0].external_attr >> 16)):
        raise ValueError('JP archive member missing, duplicated or exceeds limit')
    return matches[0]


def prepare_client(archive, apksig, stage, *, anchor, expected_version, previous_code):
    """All checks run against a temporary seed; no current state is changed."""
    from analysis.crypto.deobfuscate_paged_il2cpp_metadata import decode, read_sections
    from analysis.crypto.inspect_il2cpp import MetadataV39
    from analysis.parse_ournotes_apk import parse_unityfs_header
    from tools.bundle_decoder import resolve_bundle_decoder
    from tools.current_client import _verify_packaged_bundles
    from analysis.crypto.decrypt_global_formal_scores import decrypt_header
    archive, apksig, stage, anchor = map(Path, (archive, apksig, stage, anchor))
    if archive.is_symlink() or not 0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError('JP package archive exceeds limit')
    if file_hash(apksig) != JP_APKSIG_SHA256:
        raise ValueError('Android APK signature verifier digest mismatch')
    if file_hash(anchor) != JP_METADATA_SHA256:
        raise ValueError('JP trusted metadata anchor mismatch')
    apk_root = stage/'apks'
    apk_root.mkdir()
    with zipfile.ZipFile(archive) as xapk:
        members = [_member(xapk, name, MAX_ARCHIVE_BYTES) for name in XAPK_APKS]
        if sum(i.file_size for i in members) > MAX_EXTRACTED_BYTES:
            raise ValueError('JP package expanded size exceeds limit')
        actual_apks = {i.filename for i in xapk.infolist() if i.filename.endswith('.apk')}
        if actual_apks != set(XAPK_APKS):
            raise ValueError('JP package split layout changed')
        for info in members:
            with xapk.open(info) as source, (apk_root/XAPK_APKS[info.filename]).open('xb') as output:
                shutil.copyfileobj(source, output)
    package = build_package_set_manifest(apk_root, region='jp', channel='production')
    if (package.get('packageName') != 'com.bushiroad.sirius'
            or package.get('certificateSha256') != JP_CERTIFICATE_SHA256
            or package.get('versionName') != expected_version
            or type(package.get('versionCode')) is not int or package['versionCode'] <= previous_code):
        raise ValueError('JP mirror package is not the recommended newer signed client; retry after mirror sync')
    for apk in sorted(apk_root.glob('*.apk')):
        verify_apk_signature(apk, apksig, JP_CERTIFICATE_SHA256)
    with zipfile.ZipFile(apk_root/'base.apk') as apk:
        names = [i.filename for i in apk.infolist() if i.filename.endswith('/global-metadata.dat')]
        if len(names) != 1:
            raise ValueError('JP base APK lacks unique metadata')
        raw = apk.read(_member(apk, names[0], MAX_METADATA_BYTES))
        unity_info = _member(apk, 'assets/bin/Data/data.unity3d', MAX_ARCHIVE_BYTES)
        # Only the header is needed to identify the Unity generator.
        with apk.open(unity_info) as source:
            unity_header = source.read(128)
    clear = raw if raw[:8] == struct.pack('<II',0xFAB11BAF,39) else decode(
        raw,key=0x66,version=39,page_size=4096,period_pages=16,xor_page_residues={1,2,3,4})[0]
    read_sections(clear)
    metadata = stage/'metadata.v39.dat'
    metadata.write_bytes(clear)
    unity_path = stage/'unity-header'
    unity_path.write_bytes(unity_header)
    unity = parse_unityfs_header(unity_path)
    unity_path.unlink()
    if not unity or unity.get('unity_version') != SUPPORTED_UNITY:
        raise ValueError('JP Unity identity requires a reviewed runtime')
    (stage/'unity-version.txt').write_text(SUPPORTED_UNITY+'\n')
    shutil.copyfile(anchor, stage/ANCHOR_NAME)
    binding = derive_binding(stage/ANCHOR_NAME, metadata, expected_version)
    key, seed, _ = resolve_bundle_decoder(MetadataV39(metadata), expected_version, profile=binding['decoderProfile'])
    samples = _verify_packaged_bundles(apk_root/'split_UnityDataAssetPack.apk', key, seed, decrypt_header)
    receipt = {'schemaVersion':2, 'region':'jp', 'status':'verified_seed',
               'signatureVerified':True, 'clientVersion':expected_version, 'versionCode':package['versionCode'],
               'certificateSha256':JP_CERTIFICATE_SHA256, 'metadataSha256':file_hash(metadata),
               'packageSetSha256':package['packageSetSha256'], 'xapkSha256':file_hash(archive),
               'unityVersion':SUPPORTED_UNITY, 'binding':binding, 'verifiedBundleSamples':samples,
               'apks':{r['logicalName']:r['sha256'] for r in package['splits']}}
    write_json(stage/PROFILE_NAME, receipt)
    return receipt


def install_seed(stage, seed):
    """Rollback a failed replacement; retain backup if rollback itself fails."""
    stage, seed = Path(stage), Path(seed)
    backup = stage/'backup'
    backup.mkdir()
    moved, installed = [], []
    try:
        for name in SEED_FILES:
            target = seed/name
            if target.is_symlink():
                raise ValueError('linked JP seed member')
            if target.exists():
                os.replace(target, backup/name)
                moved.append(name)
            os.replace(stage/name, target)
            installed.append(name)
    except BaseException:
        for name in reversed(installed):
            os.replace(seed/name, stage/name)
        for name in reversed(moved):
            os.replace(backup/name, seed/name)
        raise
    shutil.rmtree(backup)


def upgrade_from_archive(seed, archive, apksig, expected_version, previous_code):
    seed = Path(seed)
    if seed.is_symlink() or not seed.is_dir():
        raise ValueError('JP seed directory missing or linked')
    current = seed/'metadata.v39.dat'
    anchor = current if file_hash(current) == JP_METADATA_SHA256 else seed/ANCHOR_NAME
    stage = Path(tempfile.mkdtemp(prefix='.jp-upgrade-', dir=seed.parent))
    try:
        prepare_client(archive, apksig, stage, anchor=anchor,
                       expected_version=expected_version, previous_code=previous_code)
        client = client_from_metadata(stage/'metadata.v39.dat', authorize_builtin_credentials=True)
        observation = client.discover()
        if observation.get('clientVersion') != expected_version:
            raise ValueError('JP upgraded client probe identity mismatch')
        install_seed(stage, seed)
        return observation
    finally:
        # Never discard the only remaining old files after a failed rollback.
        backup = stage/'backup'
        if not backup.exists() or not any(backup.iterdir()):
            shutil.rmtree(stage)


def ensure_current(seed):
    seed = Path(seed)
    package, _ = validate_package(seed/'metadata.v39.dat', seed/'apks')
    client = client_from_metadata(seed/'metadata.v39.dat', authorize_builtin_credentials=True)
    try:
        return client.discover()
    except JpClientUpdateRequired as update:
        version = update.version
    old_version = tuple(map(int, client.client_version.split('.')))
    if tuple(map(int, version.split('.'))) <= old_version:
        raise ValueError('JP recommended client is not newer than the verified client')
    with tempfile.TemporaryDirectory(prefix='.jp-acquire-', dir=seed.parent) as tmp:
        archive, apksig = Path(tmp)/'client.xapk', Path(tmp)/'apksig.jar'
        download_file(LATEST_XAPK, archive)
        download_file(JP_APKSIG_URL, apksig, hosts=frozenset({'dl.google.com'}), limit=16*1024*1024)
        return upgrade_from_archive(seed, archive, apksig, version, package['versionCode'])
