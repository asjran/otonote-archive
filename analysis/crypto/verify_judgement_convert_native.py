#!/usr/bin/env python3
"""Run intact generic TryConvert -> Target TryConvertCore for build 25.

Managed dictionaries, interface properties, target membership and remaining-
count display aggregation are host fixtures, not a complete IL2CPP runtime.
The native eligibility, increment, limit test and unregister order run intact.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crypto.native_scoring_harness import NativeHarness, ROOT, CLIENT_SHA, DECODED

def run():
    h = NativeHarness()
    try:
        klass, iface, slot = h.alloc(0x400), h.alloc(), h.alloc()
        h.u64(iface, klass)
        for addr in [0xc537478, 0xc5374c0, 0xc5c9a68, 0xc5356d0, 0xc5376d0, 0xc5376d8]: h.u64(addr, iface)
        for addr in [0xccc4df0, 0xccb50b6]: h.write(addr, b'\1')
        applier, note, executor, owner_map, params, finished, method, generic_class, rgctx = [h.alloc(0x180) for _ in range(9)]
        for obj in [applier, note, executor]: h.u64(obj, klass)
        h.u64(applier + 0x10, executor); h.u64(applier + 0x18, owner_map)
        h.u64(applier + 0x20, params); h.u64(applier + 0x28, finished)
        h.u64(method + 0x20, generic_class); h.u64(generic_class + 0xc0, rgctx)
        h.u64(klass + 0x1a8, 0x560908c); h.u64(klass + 0x1d8, 0x5609250)
        data = {'active': True, 'grade': 5, 'type': 1, 'time': 1234, 'excluded': False, 'events': []}
        record = b''
        def resolve(h):
            obj, index = h.reg(0), h.reg(2)
            if obj == note:
                value = data[{1: 'type', 3: 'grade', 5: 'time'}[index]]
                callback = lambda h, v=value: h.ret(v)
            elif obj == executor and index == 2:
                def callback(h): data['events'].append('unregister'); h.ret()
            else: raise ValueError((hex(obj), index))
            h.u64(slot, h.stub(callback)); h.ret(slot)
        h.callbacks[0x5412b78] = resolve
        def get(h):
            if data['active']: h.uc.mem_write(h.reg(2), record)
            h.ret(int(data['active']))
        def put(h):
            nonlocal record
            record = bytes(h.uc.mem_read(h.reg(2), 32)); data['events'].append('increment'); h.ret()
        def remove(h): data['active'] = False; data['events'].append('removeParam'); h.ret(1)
        def finished_put(h): data['finishedAt'] = h.reg(2); data['events'].append('deferFinish'); h.ret()
        def target(h): h.ret(int(data['grade'] == 5))
        def view(h): h.reg(1, 0); h.ret(0)
        h.callbacks.update({0x79aec4c: get, 0x79ad03c: put, 0x79ae604: remove,
            0x7a9148c: lambda h: h.ret(1), 0x7a9004c: finished_put,
            0x8c43478: lambda h: h.ret(), 0x5608a58: target,
            0x75a8f64: view, 0x75b1918: lambda h: h.ret(int(data['excluded']))})
        rows = []
        for maximum in [0, 1, 2, 3]:
            for count in [0, 1, 2, 3]:
                for grade in [3, 5, 6]:
                    for excluded in [False, True]:
                        record = struct.pack('<qiiQii', 42, count, maximum, 0, 6, 0)
                        data.update(active=True, grade=grade, excluded=excluded, events=[], finishedAt=None)
                        result = h.call(0x8c430f8, applier, 7, note, method)
                        stored_count = struct.unpack_from('<i', record, 8)[0]
                        events = list(data['events'])
                        second = h.call(0x8c430f8, applier, 7, note, method)
                        eligible = grade == 5 and not excluded
                        exhausted = eligible and maximum > 0 and count + 1 >= maximum
                        assert result == (6 if eligible else grade)
                        assert stored_count == count + int(eligible)
                        assert events == ([] if not eligible else ['increment'] +
                            (['unregister', 'removeParam', 'deferFinish'] if exhausted else []))
                        assert second == (6 if eligible and not exhausted else grade)
                        rows.append({'maximum': maximum, 'count': count, 'grade': grade,
                            'excluded': excluded, 'result': result, 'storedCount': stored_count,
                            'events': events, 'secondResult': second})
        return {'clientSha256': CLIENT_SHA,
            'decodedSha256': hashlib.sha256(DECODED.read_bytes()).hexdigest(),
            'methods': {'tryConvert': '0x8c430f8', 'targetTryConvertCore': '0x560908c'},
            'scope': 'Complete TryConvert and TryConvertCore; managed collections/properties and remaining-display aggregation are host fixtures.',
            'cases': rows}
    finally: h.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path,
        default=ROOT / 'output/verification/chart-native-20261002/convert-native.json')
    args = p.parse_args(); result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'cases': len(result['cases']), 'mismatches': 0, 'out': str(args.out)}))
