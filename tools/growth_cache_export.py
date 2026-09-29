"""Development diagnostic: export allowlisted growth from an Android cache.

Run: python3 -m tools.growth_cache_export --adb --output growth.json
No game HTTP requests, password handling, or reads of local_important.
Requires adb and the repository's py3rijndael dependency for encrypted input.
This is a development comparison path, not the intended end-user login flow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.growth_export import ExportError, MAX_BYTES, MAX_RECORDS, MAX_SAFE_INTEGER, write_snapshot

PACKAGE = 'com.bilibili.sirius'
CACHE_PATH = ('/sdcard/Android/data/' + PACKAGE + '/files/'
              + hashlib.sha256(b'LocalData').hexdigest() + '/'
              + hashlib.sha256(b'cache').hexdigest())
PROFILE = 'global-android-1.0.1-25-local-cache'
GROUPS = {
    '_memberCards': ('memberCards', {
        '_masterId': 'masterId', '_exp': 'exp', '_awakeCount': 'awakeCount',
        '_rank': 'cardRank', '_liveSkillLevel': 'liveSkillLevel',
        '_performanceSkillLevel': 'performanceSkillLevel',
    }),
    '_supportCards': ('supportCards', {
        '_masterId': 'masterId', '_exp': 'exp', '_rank': 'cardRank',
        '_duplicateCount': 'duplicateCount',
    }),
    '_bandItems': ('bandItems', {'_masterId': 'masterId', '_level': 'level'}),
    '_characters': ('characterRanks', {'_masterId': 'characterId', '_exp': 'exp'}),
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExportError('duplicate_json_key')
        result[key] = value
    return result


def extract_cache_document(document: dict) -> dict:
    if not isinstance(document, dict) or not isinstance(document.get('_player'), dict):
        raise ExportError('missing_cached_player')
    player = document['_player']
    growth = {name: None for name, _ in GROUPS.values()}
    coverage = {name: 'not_observed' for name in growth}
    missing = {}
    total = 0
    for source, (name, mapping) in GROUPS.items():
        if source not in player or player[source] is None:
            continue
        records = player[source]
        if not isinstance(records, list):
            raise ExportError('invalid_cached_collection')
        total += len(records)
        if total > MAX_RECORDS:
            raise ExportError('too_many_growth_records')
        identity = mapping['_masterId']
        seen = set()
        output = []
        absent = set()
        for record in records:
            if not isinstance(record, dict):
                raise ExportError('invalid_cached_record')
            item = {}
            for key, target in mapping.items():
                value = record.get(key)
                if key not in record or value is None:
                    item[target] = None
                    absent.add(target)
                    continue
                maximum = MAX_SAFE_INTEGER if key == '_masterId' else (1 << 31) - 1
                if type(value) is not int or not 0 <= value <= maximum:
                    raise ExportError('invalid_cached_growth_integer')
                item[target] = value
            public_id = item[identity]
            if public_id is None or public_id <= 0 or public_id in seen:
                raise ExportError('missing_or_duplicate_public_master_id')
            seen.add(public_id)
            if name == 'memberCards':
                # Native get_GekisouSkillLevel reads the persisted performance field.
                item['gekisouSkillLevel'] = item['performanceSkillLevel']
                if item['gekisouSkillLevel'] is None:
                    absent.add('gekisouSkillLevel')
                item['leaderSkillLevel'] = None  # derived from Master rank, not cache
                item['linkSkillLevel'] = None
                absent.update(('leaderSkillLevel', 'linkSkillLevel'))
            output.append(item)
        growth[name] = sorted(output, key=lambda r: r[identity])
        coverage[name] = 'observed_partial_fields' if absent else 'observed'
        if absent:
            missing[name] = sorted(absent)
    growth['tgw'] = None
    coverage['tgw'] = 'not_persisted_in_verified_cache'
    return {
        'format': 'ournotes-growth-snapshot', 'schemaVersion': 1,
        'decoderProfile': PROFILE,
        'exportedAt': datetime.now(timezone.utc).isoformat(),
        'verification': 'local_cache_not_server_verified', 'complete': False,
        'source': {'kind': 'android_local_cache', 'freshness': 'unknown'},
        'coverage': coverage, 'missingFields': missing, 'growth': growth,
    }


def decode_cache(data: bytes) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise ExportError('invalid_cache_size')
    from analysis.crypto.decrypt_master import DEFAULT_SALT, DEFAULT_IV, DEFAULT_KEY, decrypt_cbc
    if len(data) < 96 or data[:32] != DEFAULT_SALT or data[32:64] != DEFAULT_IV:
        raise ExportError('unsupported_cache_header')
    try:
        plain = decrypt_cbc(data[64:], DEFAULT_KEY, DEFAULT_IV)
        document = json.loads(plain, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise ExportError('invalid_encrypted_cache') from None
    return extract_cache_document(document)


def read_adb_cache(serial: str | None) -> tuple[bytes, dict]:
    if serial and not re.fullmatch(r'[A-Za-z0-9_.:\-]+', serial):
        raise ExportError('invalid_device_selector')
    adb = ['adb'] + (['-s', serial] if serial else [])

    def run(arguments, limit=MAX_BYTES):
        # Stream bounded output; adb stderr can contain local device identifiers.
        # Neither stderr nor raw cache bytes are included in error messages.
        import threading
        with subprocess.Popen(adb + arguments, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as process:
            timer = threading.Timer(30, process.kill)
            timer.start()
            try:
                value = process.stdout.read(limit + 1)
                if len(value) > limit:
                    process.kill()
                    raise ExportError('adb_output_too_large')
                if process.wait() != 0:
                    raise ExportError('adb_read_failed')
                return value
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()

    package = run(['shell', 'dumpsys', 'package', PACKAGE], 2 * 1024 * 1024)
    if not re.search(rb'\bversionCode=25\b', package) or not re.search(rb'\bversionName=1\.0\.1\s', package):
        raise ExportError('unsupported_installed_game_version')

    def stat():
        value = run(['shell', 'stat', '-c', '%s:%Y', CACHE_PATH], 100).strip()
        if not re.fullmatch(rb'[0-9]+:[0-9]+', value):
            raise ExportError('cache_stat_failed')
        size, modified = (int(x) for x in value.split(b':'))
        if not 96 <= size <= MAX_BYTES:
            raise ExportError('invalid_cache_size')
        return size, modified

    before = stat()
    data = run(['exec-out', 'cat', CACHE_PATH])
    after = stat()
    if before != after or len(data) != after[0]:
        raise ExportError('cache_changed_during_read')
    if data != run(['exec-out', 'cat', CACHE_PATH]) or stat() != after:
        raise ExportError('cache_changed_during_read')
    return data, {'cacheModifiedAt': datetime.fromtimestamp(after[1], timezone.utc).isoformat(),
                  'installedVersion': '1.0.1', 'installedVersionCode': 25}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--adb', action='store_true')
    source.add_argument('--input', type=Path, help='previously copied encrypted cache')
    parser.add_argument('--serial', help='ADB device selector, used only with --adb')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.serial and not args.adb:
        parser.error('--serial requires --adb')
    try:
        if args.adb:
            data, source_info = read_adb_cache(args.serial)
        else:
            with args.input.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            source_info = {}
        snapshot = decode_cache(data)
        snapshot['source'].update(source_info)
        write_snapshot(args.output, snapshot)
    except (ExportError, OSError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, ExportError) else 'local_io_failed'
        print('Export refused: ' + code)
        return 2
    counts = {key: len(value) for key, value in snapshot['growth'].items() if isinstance(value, list)}
    print(json.dumps({'exportedCounts': counts, 'complete': False, 'tgw': 'unavailable_in_cache'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
