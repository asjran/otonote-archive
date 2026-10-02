"""Execute build-25 life commands/cache and combo recomputation intact.

The hosted functions implement only generic List<T> insertion/enumeration and
metadata access. Damage/recovery arithmetic, cache cursor and branch semantics,
combo reset/flags and strict historical queries execute original instructions.
"""
from __future__ import annotations
import argparse
import json
import random
import struct
from pathlib import Path
from crypto.native_scoring_harness import NativeHarness, CLIENT_SHA

def verify():
    h = NativeHarness()
    klass = h.alloc(0x200)
    h.i32(klass + 0xe4, 1)
    token = h.alloc(); h.u64(token, klass)
    for address in [0xc535958, 0xc535968, 0xc535970, 0xc535978, 0xc535980, 0xc535988]:
        h.u64(address, token)
    # Host metadata initialization; it has no gameplay effects.
    h.callbacks[0x53d52c0] = lambda vm: vm.ret()
    h.callbacks[0x53d5440] = lambda vm: vm.ret()
    controller, parameter = h.alloc(), h.alloc()
    h.u64(controller + 0x10, parameter)
    h.i32(parameter + 0x14, 1000); h.i32(parameter + 0x18, 1000)
    guard, reduction = h.alloc(16), h.alloc(16)
    rng = random.Random(20261002)
    commands = []
    for i in range(512):
        state = dict(life=rng.choice([0, 1, 50, 700, 1000, 1800, 2000]), guard=rng.choice([0,0,1,2]), reduction=rng.choice([0,0,1000,9999,10000,11000]))
        command = dict(kind=i % 7, value=rng.choice([1,50,100,333,800,1500]), safety=bool(i % 2), overHeal=bool(i % 3))
        h.i32(guard, state['guard']); h.i32(reduction, state['reduction'])
        packed = command['value'] | (int(command['safety']) << 32) | (int(command['overHeal']) << 40)
        result = h.call(0x55c7b04, controller, state['life'], command['kind'] << 32, packed, guard, reduction)
        commands.append(dict(state=state, command=command, expected=dict(life=result, guard=h.i32(guard), reduction=h.i32(reduction))))

    lists = {}
    array = h.alloc(0x20 + 8 * 256); h.i32(array + 0x18, 256)
    for i in range(256):
        obj = h.alloc(0x30); lists[obj] = []; h.u64(array + 0x20 + i * 8, obj)
    h.u64(controller + 0x58, array); h.i32(controller + 0x60, 256)
    def insert(vm):
        obj, index, word0, word1 = [vm.reg(i) for i in range(4)]
        lists[obj].insert(index, (word0, word1)); vm.i32(obj + 0x18, len(lists[obj])); vm.ret()
    def get(vm):
        words = lists[vm.reg(0)][vm.reg(1)]
        vm.reg(1, words[1]); vm.ret(words[0])
    def enumerator(vm):
        vm.uc.mem_write(vm.reg(8), struct.pack('<QIIQQ', vm.reg(0), 0, 0, 0, 0)); vm.ret()
    def move(vm):
        address = vm.reg(0); obj, index = struct.unpack('<QI', vm.uc.mem_read(address,12))
        if index >= len(lists[obj]): vm.ret(0); return
        vm.uc.mem_write(address + 16, struct.pack('<QQ', *lists[obj][index])); vm.uc.mem_write(address + 8, struct.pack('<i',index + 1)); vm.ret(1)
    h.callbacks.update({0x87bf068:insert, 0x87bdda4:get, 0x87becc8:enumerator, 0x7d35f3c:move, 0x7d35f38:lambda vm:vm.ret()})
    histories = []
    for case in range(32):
        for obj in lists: lists[obj].clear(); h.i32(obj + 0x18, 0)
        h.i32(controller + 0x64, -1); h.i32(controller + 0x68, 1000); h.i32(controller + 0x6c, 0); h.i32(controller + 0x70, 0)
        operations = []
        for i in range(48):
            time = rng.randrange(0, 900) if i % 7 == 0 else i * 20 + rng.randrange(0, 20)
            command = dict(timeMs=time, kind=rng.choice([0,0,0,2]), value=rng.choice([50,100,300]), overHeal=True)
            h.call(0x55c73a8, controller, time | command['kind'] << 32, command['value'] | 1 << 40)
            operations.append(dict(add=command))
            query = i * 20 + rng.choice([0,10,50,100])
            value = h.call(0x55c77e4, controller, query)
            operations.append(dict(timeMs=query, expected=value))
        histories.append(operations)

    counter = h.alloc(); entries = h.alloc(0x20 + 12 * 64); states = h.alloc(0x20 + 12 * 64)
    h.u64(counter + 0x10, entries); h.u64(counter + 0x18, states)
    h.i32(entries + 0x18, 64); h.i32(states + 0x18, 64)
    combos = []
    for case in range(128):
        values = [rng.randrange(1,7) for _ in range(32)]
        times = [i // 3 * 10 for i in range(32)]
        h.i32(counter + 0x20, 32)
        for i, value in enumerate(values): h.write(entries + 0x20 + 12 * i, struct.pack('<iii',times[i],value,i))
        h.call(0x6a57284, counter, 0)
        expected = []
        for i in range(32):
            combo, maximum, flags = struct.unpack('<III', h.uc.mem_read(states + 0x20 + i * 12,12))
            expected.append(dict(combo=combo,maxCombo=maximum,allPerfect=bool(flags&1),fullCombo=bool(flags&256)))
        queries = [dict(timeMs=time,expected=h.call(0x6a57398,counter,time)) for time in [0,10,11,20,80,81,110]]
        combos.append(dict(judgements=values,times=times,expected=expected,queries=queries))
    h.close()
    return dict(clientSha256=CLIENT_SHA,commands=commands,histories=histories,combos=combos,
        substitutions=['IL2CPP metadata setup','generic List insertion, index access, enumeration and disposal'],
        scope='original ApplyCommand, AddCommand, GetLifeAtMs, RecomputeStateFrom and GetTimingCombo; not Unity scheduler')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=verify();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({key:len(result[key]) for key in ['commands','histories','combos']}))
