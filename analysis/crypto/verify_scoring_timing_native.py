"""Execute intact MusicStopwatch and SkillEffectUpdater.UpdateExecuting methods.

Only interface getters for explicit frame time/duration and metadata plumbing
are hosted. Stopwatch accumulation, comparison, branching, ceil and writes run
the original client instructions. No original game resources are exported.
"""
from __future__ import annotations
import argparse
import json
import struct
import random
from pathlib import Path
from crypto.native_scoring_harness import NativeHarness, CLIENT_SHA
from unicorn.arm64_const import UC_ARM64_REG_S0

f32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]
bits = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]

def verify():
    h = NativeHarness()
    stopwatch = h.alloc()
    clocks = []
    for fps in [30, 60, 120]:
        h.call(0x6a63bac, stopwatch)
        entries = []
        for frame in range(1, 1001):
            dt = f32(1 / fps)
            h.uc.reg_write(UC_ARM64_REG_S0, bits(dt))
            h.call(0x6a63bb8, stopwatch)
            elapsed_ms = h.call(0x6a63b6c, stopwatch)
            entries.append(dict(frame=frame, elapsedBits=bits(h.f32(stopwatch + 0x10)), elapsedMs=elapsed_ms))
        clocks.append(dict(frameRate=fps, deltaSeconds=dt, entries=entries))
    klass = h.alloc(0x200)
    h.i32(klass + 0xe4, 1)
    def obj():
        address = h.alloc(0x100)
        h.u64(address, klass)
        return address
    updater, state, definition, frame_input = [obj() for _ in range(4)]
    h.u64(updater + 0x10, definition)
    h.u64(updater + 0x18, state)
    token = h.alloc()
    h.u64(token, klass)
    for address in [0xc537440, 0xc536c00, 0xc537040, 0xc531b88]:
        h.u64(address, token)
    for address in [0xccb511d, 0xccb4cd3]:
        h.write(address, b'\x01')
    current = {}
    def duration(vm):
        vm.uc.reg_write(UC_ARM64_REG_S0, bits(current['seconds']))
        vm.ret()
    callbacks = {(frame_input, 0): lambda vm: vm.ret(current['nowMs']),
                 (frame_input, 14): lambda vm: vm.ret(current['musicLengthMs']),
                 (definition, 15): duration}
    pairs = {}
    for key, cb in callbacks.items():
        pair = h.alloc(16)
        h.u64(pair, h.stub(cb))
        pairs[key] = pair
    h.callbacks[0x5412b78] = lambda vm: vm.ret(pairs[(vm.reg(0), vm.reg(2))])
    rng = random.Random(20261002)
    effects = []
    for i in range(1024):
        start = rng.randrange(0, 200000)
        seconds = f32(rng.choice([0.0004, 0.015, 0.016, 0.0167, 4.9997, 5, 5.0004, 5.125, 7.9, 9.2]))
        extension = f32(rng.choice([0, 0.1, 1.25, 333.333, 1000]))
        raw = f32(f32(seconds * 1000) + extension)
        now = start + int(raw) + [-1, 0, 1, 20][i % 4]
        force = i % 13 == 0
        length = now - 1 if i % 17 == 0 else 600000
        current.update(seconds=seconds, nowMs=now, musicLengthMs=length)
        h.i32(state + 0x2c, 3)
        h.i32(state + 0x30, start)
        h.i32(state + 0x34, -1)
        h.f32(state + 0x4c, extension)
        result = h.call(0x561f914, updater, frame_input, int(force))
        effects.append(dict(startMs=start, seconds=seconds, extensionMs=extension, nowMs=now,
            force=force, musicLengthMs=length, ended=bool(result), finishMs=h.i32(state + 0x34),
            state=h.i32(state + 0x2c)))
    h.close()
    return dict(clientSha256=CLIENT_SHA, stopwatchUpdates=3000, effectCases=len(effects), clocks=clocks, effects=effects,
        substitutions=['interface getters for explicit time, music length and effect duration', 'IL2CPP metadata initialization flags'],
        scope='original stopwatch methods and UpdateExecuting; no Unity frame scheduler or full skill pool')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['clocks','effects']}))
