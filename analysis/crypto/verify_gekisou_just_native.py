#!/usr/bin/env python3
"""Execute intact build-25 fever transition and JUST toggle methods.

Fixture services replace only property/interface/cache lookup and the final
SetEnableJudgement sink. The state machine and toggle branches run natively.
This is not the complete Unity frame loop or skill converter lifecycle.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crypto.native_scoring_harness import NativeHarness, ROOT, CLIENT_SHA, DECODED

def run():
    h = NativeHarness()
    try:
        klass, iface, slot = h.alloc(0x400), h.alloc(), h.alloc()
        h.u64(iface, klass)
        for a in [0xc535db8, 0xc535870, 0xc5362d8, 0xc535fa0, 0xc554160]: h.u64(a, iface)
        for a in [0xccc1395, 0xccbbd0e]: h.write(a, b'\1')
        updater, fever, event, start, end = [h.alloc() for _ in range(5)]
        node, context, executor, state, range_, cache = [h.alloc() for _ in range(6)]
        for p in [event, start, end, state, range_]: h.u64(p, klass)
        h.u64(updater + 0x10, event); h.u64(updater + 0x20, fever)
        h.u64(node + 0x10, context); h.u64(context + 0x10, executor)
        h.i32(start + 0x14, 1000); h.i32(end + 0x14, 2000)
        def resolve(h):
            obj, method = h.reg(0), h.reg(2)
            if obj == event: result = start if method == 1 else end
            elif obj in [start, end]: result = h.i32(obj + 0x14)
            elif obj == state: result = range_ if method == 0 else h.i32(state + 0x20)
            elif obj == range_: result = h.i32(range_ + 0x30)
            else: raise ValueError((obj, method))
            h.u64(slot, h.stub(lambda h, r=result: h.ret(r))); h.ret(slot)
        h.callbacks[0x5412b78] = resolve
        h.callbacks[0x924ec24] = lambda h: h.ret(cache)
        h.callbacks[0x606cea0] = lambda h: h.ret(cache)
        force = False
        h.callbacks[0x5c7e318] = lambda h: h.ret(int(force))
        toggles = []
        def toggle(h):
            toggles.append({'grade': h.reg(1), 'enabled': bool(h.reg(2))}); h.ret()
        h.callbacks[0x55cbaa0] = toggle
        fever_rows = []
        for initial in [1, 2, 3]:
            for time in [999, 1000, 1001, 1999, 2000, 2001, 2500]:
                h.i32(fever + 0x14, initial)
                h.call(0x6a577c8, updater, time)
                fever_rows.append({'initial': initial, 'timeMs': time, 'state': h.i32(fever + 0x14)})
        toggle_rows = []
        for mission in [1, 2, 3, 4]:
            h.i32(range_ + 0x30, mission)
            for value in range(1, 9):
                h.i32(state + 0x20, value)
                for force in [False, True]:
                    toggles.clear(); h.call(0x612d5cc, node, state)
                    toggle_rows.append({'mission': mission, 'state': value, 'force': force, 'calls': list(toggles)})
        return {
            'clientSha256': CLIENT_SHA,
            'decodedSha256': hashlib.sha256(DECODED.read_bytes()).hexdigest(),
            'nativeMethods': {'feverUpdate': '0x6a577c8', 'justToggle': '0x612d5cc'},
            'scope': 'Complete native methods with fixture-backed interfaces, property/cache access, toggle sink; not full frame loop.',
            'fever': fever_rows, 'toggles': toggle_rows,
        }
    finally: h.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path,
        default=ROOT / 'output/verification/chart-native-20261002/just-native.json')
    args = p.parse_args(); result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'feverCases': len(result['fever']), 'toggleCases': len(result['toggles']), 'out': str(args.out)}))
