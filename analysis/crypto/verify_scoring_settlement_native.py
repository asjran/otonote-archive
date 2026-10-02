"""Execute the original multiplayer submission -> fetch -> endpoint query chain.

Unity interface plumbing and the score provider are explicit host fixtures.
The original functions decide IF/WHEN to query, query order, tuple construction,
and overwrite of controller snapshots. This is NOT an end-to-end score test.
"""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path
from crypto.native_scoring_harness import NativeHarness, CLIENT_SHA
from unicorn.arm64_const import UC_ARM64_REG_PC


def verify():
    h = NativeHarness()
    klass = h.alloc(0x200)
    def obj():
        address = h.alloc(0x200)
        h.u64(address, klass)
        return address
    node, scene, ctrl, source, state, info, start_note, end_note, executor, score_ctrl, score_result, notify = [obj() for _ in range(12)]
    array = h.alloc()
    h.i32(array + 0x18, 1)
    h.u64(array + 0x20, state)
    h.u64(node + 0x10, scene)
    h.u64(scene + 0x80, ctrl)
    h.u64(scene + 0x10, executor)
    h.u64(ctrl + 0x118, source)
    h.u64(ctrl + 0x18, array)
    h.u64(ctrl + 0x20, notify)
    h.u64(executor + 0x30, score_ctrl)
    changes = h.alloc()
    h.i32(changes, 0)
    for address in [0xccbbd72, 0xccbbd1b, 0xccb4ecc]:
        h.write(address, b'\x01')
    token = h.alloc()
    h.u64(token, token)
    for address in [0xc5362c0, 0xc5362d8, 0xc535fa8, 0xc535fa0, 0xc535870, 0xc535b60, 0xc535b68]:
        h.u64(address, token)
    current = {}
    def spans(vm):
        vm.reg(1, 1)
        vm.ret(changes)
    getters = {
        (ctrl, 6): spans,
        (ctrl, 14): lambda vm: vm.ret(state),
        (state, 1): lambda vm: vm.ret(current['state']),
        (source, 0): lambda vm: vm.ret(info),
        (info, 1): lambda vm: vm.ret(start_note),
        (info, 2): lambda vm: vm.ret(end_note),
        (start_note, 4): lambda vm: vm.ret(current['startMs']),
        (end_note, 4): lambda vm: vm.ret(current['endMs']),
        (score_result, 1): lambda vm: vm.ret(current['score']),
    }
    methods = {}
    for key, callback in getters.items():
        pair = h.alloc(16)
        h.u64(pair, h.stub(callback))
        methods[key] = pair
    def interface(vm):
        key = vm.reg(0), vm.reg(2)
        if key not in methods:
            raise RuntimeError(f'unexpected interface fixture {key}')
        vm.ret(methods[key])
    h.callbacks[0x5412b78] = interface
    def calculate(vm):
        time = vm.reg(1)
        current['queries'].append(time)
        current['score'] = current['scores'][time]
        vm.ret(score_result)
    h.callbacks[0x55e5b28] = calculate
    def notification(vm):
        current['notifications'] += 1
        vm.ret()
    h.callbacks[0x55d78c0] = notification
    # The remaining upload code serializes the already-updated range. Stop here
    # rather than emulate transport or manufacture a server response.
    h.observers[0x613cb24] = lambda vm: vm.uc.reg_write(UC_ARM64_REG_PC, vm.stop)
    rng = random.Random(20261002)
    rows = []
    for index in range(192):
        start = rng.randrange(0, 200000)
        end = start + rng.randrange(1, 50000)
        s0 = rng.randrange(1000, 1000000)
        s1 = s0 + rng.randrange(1, 1000000)
        phase = [6, 7, 8][index % 3]
        current.clear()
        current.update(state=phase, startMs=start, endMs=end, scores={start:s0,end:s1}, queries=[], notifications=0)
        h.i32(state + 0x54, 111)
        h.i32(state + 0x58, 999)
        h.call(0x613c948, node, ctrl)
        actual = [h.i32(state + 0x54), h.i32(state + 0x58)]
        expected = [s0, s1] if phase == 7 else [111, 999]
        assert actual == expected, (index, actual, expected)
        assert current['queries'] == ([start, end] if phase == 7 else [])
        assert current['notifications'] == (1 if phase == 7 else 0)
        rows.append(dict(state=phase, startMs=start, endMs=end, queried=current['queries'], frozenBefore=[111,999], storedAfter=actual))
    h.close()
    return dict(clientSha256=CLIENT_SHA, cases=len(rows), differences=0,
        conclusion='Multiplayer state 7 queries START then END and replaces controller snapshots before upload; state 6/8 do not.',
        originalMethods=['0x613c948 OnTryConnectGekisouResult', '0x612ee30 FetchGekisouRangeScore', '0x55ccb28 GetScoreAtTimeMs', '0x9854520 tuple constructor', '0x55d98f0 UpdateRangeScore'],
        substitutions=['IL2CPP interface dispatch and input object getters', 'CalculateLiveScore returns distinct endpoint sentinels, does not validate score arithmetic', 'range update notification sink', 'stop before network serialization'],
        vectors=rows)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'vectors'}))
