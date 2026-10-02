#!/usr/bin/env python3
"""Execute build-25 chart ordering/geometry/generation kernels offline.

This is not the complete IL2CPP deserializer/converter. Host substitutions are
recorded in the output. The priority selector and easing function run in full;
the native eighth-note iterator runs with fixture timing/property services.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crypto.native_scoring_harness import NativeHarness, DECODED, CLIENT_SHA, ROOT
from unicorn.arm64_const import UC_ARM64_REG_S0, UC_ARM64_REG_D0, UC_ARM64_REG_PC

NODE = Path(os.environ.get('OURNOTES_NODE', 'node'))
DECODED_SHA = '393a166e12f1886597709aa82e93bc58283631d629238e10e22fa10efc3f24eb'
def f32(x): return struct.unpack('<f', struct.pack('<f', x))[0]
def set_s0(h, x): h.uc.reg_write(UC_ARM64_REG_S0, struct.unpack('<I', struct.pack('<f', x))[0])
def get_s0(h): return struct.unpack('<f', struct.pack('<I', h.uc.reg_read(UC_ARM64_REG_S0)))[0]
def set_d0(h, x): h.uc.reg_write(UC_ARM64_REG_D0, struct.unpack('<Q', struct.pack('<d', x))[0])
def get_d0(h): return struct.unpack('<d', struct.pack('<Q', h.uc.reg_read(UC_ARM64_REG_D0)))[0]
def stop(h): h.uc.reg_write(UC_ARM64_REG_PC, h.stop)


def run():
    if hashlib.sha256(DECODED.read_bytes()).hexdigest() != DECODED_SHA:
        raise ValueError('decoded ELF differs from audited build 25')
    h = NativeHarness()
    try:
        klass, iface, slot, obj = h.alloc(0x400), h.alloc(), h.alloc(), h.alloc()
        h.u64(obj, klass)
        # Interface resolution is a fixture service; the property getter itself
        # is the unchanged native NoteInfoData.get_OperateType method.
        h.u64(slot, 0x6a56e24)
        h.u64(0xc5bd6c8, iface)
        h.u64(iface, klass)
        h.write(0xccc1359, b'\1')
        h.callbacks[0x5412b78] = lambda h: h.ret(slot)
        priorities = []
        for kind in range(131):
            h.i32(obj + 0x38, kind)
            priorities.append({'type': kind, 'priority': h.call(0x6a50d68, 0, obj)})

        easing = []
        for kind in range(3):
            for i in range(129):
                value = f32(i / 128)
                set_s0(h, value)
                h.call(0x6a39468, kind)
                easing.append({'type': kind, 'progress': value, 'value': get_s0(h)})

        # Full native endpoint match predicate, stopped on its successful match
        # branch before appending owner IDs. Native merging requires a nonempty
        # line-index collection; list and interface plumbing are fixture-backed.
        existing, incoming, owner_list, notes, items = [h.alloc() for _ in range(5)]
        for pointer in [existing, incoming, owner_list]: h.u64(pointer, klass)
        for pointer in [existing, incoming]: h.u64(pointer + 0x10, owner_list)
        h.i32(owner_list + 0x18, 1); h.i32(notes + 0x18, 1)
        h.u64(notes + 0x10, items); h.u64(items + 0x20, existing)
        for address in [0xc5bd710, 0xc5bddd0, 0xc533400]: h.u64(address, iface)
        h.write(0xccc134a, b'\1')
        count_slot = h.alloc(); h.u64(count_slot, h.stub(lambda h: h.ret(h.i32(h.reg(0) + 0x18))))
        h.callbacks[0x5412b78] = lambda h: h.ret(count_slot)
        h.callbacks[0x87f0234] = lambda h: h.ret(h.u64(h.u64(h.reg(0) + 0x10) + 0x20 + h.reg(1) * 8))
        def matched(h): h.reg(0, 1); stop(h)
        h.observers[0x6a50630] = matched
        merge_rows = []
        fields = {'direction': 0x3c, 'easing': 0x40, 'easingRight': 0x44, 'width': 0x48, 'critical': 0x50}
        for kind in [1, 20, 21, 22, 40, 41, 42, 60, 61, 62, 63, 80, 82, 100, 101, 102, 103, 104, 105, 122]:
            for different in [None, *fields]:
                for pointer in [existing, incoming]:
                    h.i32(pointer + 0x38, kind)
                    for offset in fields.values(): h.i32(pointer + offset, 0)
                if different: h.i32(incoming + fields[different], 1)
                result = h.call(0x6a50438, notes, incoming)
                merge_rows.append({'type': kind, 'different': different, 'merged': bool(result)})
        h.observers.clear()

        # Independent counters in the original authored/slide/guide creators.
        # Guide IDs add 10001 to the *old* counter, unlike slide IDs.
        counters = []
        for initial in [0, 1, 19, 100, 1024]:
            h.i32(obj + 0x34, initial); h.reg(19, obj); h.reg(23, iface)
            h.observers[0x6a3b848] = stop; h.call(0x6a3b838)
            authored_id = h.i32(obj + 0x34)
            h.observers.clear()
            h.i32(obj + 0x38, initial); h.reg(19, obj)
            h.observers[0x6a3d654] = stop; h.call(0x6a3d648)
            slide_id = h.i32(obj + 0x38)
            h.observers.clear()
            h.i32(obj + 0x3c, initial); h.reg(19, obj)
            h.observers[0x6a40cdc] = stop; h.call(0x6a40cd0)
            h.reg(28, 10001)
            h.observers[0x6a40d08] = stop; h.call(0x6a40d04)
            counters.append({'initial': initial, 'authoredId': authored_id, 'slideId': slide_id, 'guideId': h.reg(24)})
            h.observers.clear()

        # The original multiply/add sequence from TrySetSlideNoteId. The range
        # ends before allocation and the constructor call; no ELF bytes patched.
        h.reg(25, obj)
        id_rows = []
        for line_id in [1, 2, 19, 123, 1024, 9999]:
            for candidate_index in range(64):
                h.i32(obj + 0x10, line_id)
                h.reg(25, obj)
                # x25 is read from sp+0x60 by earlier instructions, so enter at
                # the load of the ID itself and provide its live-in registers.
                h.reg(10, candidate_index)
                h.observers[0x6a44fc4] = stop
                h.call(0x6a44fb0)
                base = h.reg(26) & 0xffffffff
                # The native constructor argument adds 10000 at 0x6a450f8.
                h.reg(26, base)
                h.reg(8, 10000)
                h.observers[0x6a450fc] = stop
                h.call(0x6a450f8)
                id_rows.append({'lineId': line_id, 'candidateIndex': candidate_index, 'id': h.reg(1)})
        h.observers.clear()

        # Execute the full iterator MoveNext. Managed allocation, interface
        # lookup, GC barriers and libc modf are substituted. The supplied clock
        # is a fixed 120 BPM chart with an unchanging time signature per case;
        # timing conversion is explicitly outside this iterator test's scope.
        state, start, end = h.alloc(), h.alloc(), h.alloc()
        h.u64(start, klass); h.u64(end, klass)
        h.u64(0xc535870, iface)
        fake_type = h.alloc(0x200)
        h.i32(fake_type + 0xe4, 1)
        h.u64(0xc531b88, fake_type)
        h.u64(0xc5bd590, iface)
        h.write(0xccc1339, b'\1'); h.write(0xccb4d9e, b'\1')
        getter_slots = {}
        for index in [0, 3, 4]:
            # Use tiny explicit property services because MusicScorePosition
            # getter addresses/shape differ from NoteInfoData.
            pointer = h.alloc()
            if index == 0: stub = h.stub(lambda h: h.ret(h.i32(h.reg(0) + 0x10)))
            elif index == 3:
                def progress(h): set_s0(h, h.f32(h.reg(0) + 0x1c)); h.ret()
                stub = h.stub(progress)
            else: stub = h.stub(lambda h: h.ret(h.i32(h.reg(0) + 0x20)))
            h.u64(pointer, stub); getter_slots[index] = pointer
        h.callbacks[0x5412b78] = lambda h: h.ret(getter_slots[h.reg(2)])
        h.callbacks[0x53d555c] = lambda h: h.ret(h.alloc(0x40))
        for address in [0xaa7cbec, 0x53d5264, 0x53d5440]: h.callbacks[address] = lambda h: h.ret()
        def modf(h):
            fraction, integer = math.modf(get_d0(h))
            h.uc.mem_write(h.reg(0), struct.pack('<d', integer)); set_d0(h, fraction); h.ret()
        h.callbacks[0xbdee510] = modf
        context = {'beats': 4}
        def beats(h): set_s0(h, context['beats']); h.ret()
        def clock(h):
            seconds_per_bar = f32(f32(context['beats'] * 60) / 120)
            seconds = f32(f32(seconds_per_bar * h.reg(0)) + f32(seconds_per_bar * get_s0(h)))
            h.ret(math.floor(f32(seconds * 1000)))
        h.callbacks[0x6a487e8] = beats
        h.callbacks[0x6a3bd80] = clock
        intervals = []
        for beats_count in [2, 3, 4, 5, 7]:
            context['beats'] = beats_count
            ticks_per_bar = beats_count * 480
            for start_tick in [0, 13, 119, 240, 479]:
                end_tick = start_tick + ticks_per_bar * 2
                start_bar, start_rem = divmod(start_tick, ticks_per_bar)
                end_bar, end_rem = divmod(end_tick, ticks_per_bar)
                def time(bar, progress):
                    duration = f32(beats_count / 2)
                    return math.floor(f32(f32(f32(duration * bar) + f32(duration * progress)) * 1000))
                h.write(state, bytes(0x100)); h.u64(state + 0x28, start); h.u64(state + 0x58, end)
                h.i32(start + 0x10, start_bar); h.f32(start + 0x1c, f32(start_rem / ticks_per_bar))
                h.i32(end + 0x20, time(end_bar, f32(end_rem / ticks_per_bar)))
                points = []
                while h.call(0x6a48448, state):
                    point = h.u64(state + 0x18)
                    points.append({'bar': h.i32(point + 0x10), 'progress': h.f32(point + 0x1c), 'timeMs': h.i32(point + 0x20)})
                    if len(points) > 1000: raise ValueError('iterator failed to terminate')
                intervals.append({'beats': beats_count, 'startTick': start_tick, 'endTick': end_tick, 'points': points})
        return {'clientSha256': CLIENT_SHA, 'decodedSha256': DECODED_SHA,
                'scope': 'Native priority selector, endpoint match predicate, easing, ID counter/arithmetic and eighth-note iterator; not full conversion or input scheduling',
                'substitutions': ['managed allocation and property/interface services', 'GC and type initialization', 'libc modf', 'fixture constant-tempo time conversion and bar signature lookup'],
                'nativeMethods': {'creationPriority': '0x6a50d68', 'endpointMatch': '0x6a50438, stop on success at 0x6a50630',
                    'easing': '0x6a39468', 'eighthNoteIterator': '0x6a48448',
                    'authoredCounter': '0x6a3b838..0x6a3b848', 'slideCounter': '0x6a3d648..0x6a3d654',
                    'guideCounter': '0x6a40cd0..0x6a40cdc + 0x6a40d04',
                    'comboId': '0x6a44fb0..0x6a44fc4 + 0x6a450f8'},
                'priorities': priorities, 'easing': easing, 'mergePredicates': merge_rows, 'counters': counters, 'ids': id_rows, 'intervals': intervals}
    finally: h.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'output/verification/chart-native-20261002/native')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    result = run()
    fixture = args.output/'chart-native-kernels.json'
    fixture.write_text(json.dumps(result, indent=2)+'\n')
    command = '''
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { formalNoteCreationPriority, formalLineNodeGeometry, reconstructFormalChart } from './site/src/lib/scoring-rules/formal-chart.mjs';
const data = JSON.parse(readFileSync(process.argv[1]));
for (const row of data.priorities) assert.equal(formalNoteCreationPriority(row.type), row.priority);
for (const row of data.easing) {
  const kind = ['linear','out','in'][row.type];
  const line = {nodes:[{tick:0,position:0,size:1,easing:kind,easingRight:kind},{tick:row.progress*128,position:null,size:null},{tick:128,position:1,size:1}]};
  assert.equal(formalLineNodeGeometry(line,1).position,row.value);
}
for (const row of data.intervals) {
  const c = {notes:[{id:'long',type:'long',nodes:[row.startTick,row.endTick].map(tick=>({tick,position:0,size:6,visible:true,operateType:'normal'}))}],bpmEvents:[{tick:0,bpm:120}],timeSignatureEvents:[{tick:0,numerator:row.beats,denominator:4}]};
  const actual = reconstructFormalChart(c).filter(e=>e.type===120).map(({bar,progress,timeMs})=>({bar,progress,timeMs}));
  assert.deepEqual(actual,row.points);
}
for (const row of data.ids) assert.equal(row.id,row.lineId+10000*(row.candidateIndex+1));
for (const row of data.counters) assert.deepEqual([row.authoredId,row.slideId,row.guideId],[row.initial+1,row.initial+1,row.initial+10001]);
const mergeable = new Set([20,22,41,42,61,62,80,82,100,101,102,103,104,105]);
for (const row of data.mergePredicates) assert.equal(row.merged,mergeable.has(row.type)&&!row.different);
console.log(JSON.stringify({priorities:data.priorities.length,easing:data.easing.length,mergePredicates:data.mergePredicates.length,idCounters:data.counters.length,intervals:data.intervals.length,generatedPositions:data.intervals.reduce((s,r)=>s+r.points.length,0),comboIds:data.ids.length,mismatches:0}));
'''
    verified = subprocess.run([str(NODE), '--input-type=module', '-e', command, str(fixture)], cwd=ROOT, capture_output=True, text=True)
    if verified.returncode:
        sys.stderr.write(verified.stderr); return verified.returncode
    summary = json.loads(verified.stdout)
    summary.update(clientSha256=CLIENT_SHA, scope=result['scope'])
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2)); return 0
if __name__ == '__main__': raise SystemExit(main())
