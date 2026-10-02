"""Execute build 25's unmodified ARM64 UndoDiff leaf on an ARM64 Mac.

The C driver accumulates explicit synthetic factor deltas. Only UndoDiff is
extracted client code; this does not run Unity or validate device scheduling.
"""
import argparse, hashlib, json, platform, random, struct, subprocess, sys
from pathlib import Path
sys.path[:0] = ['analysis', 'analysis/vendor']
from crypto.inspect_il2cpp import ElfMemory
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--node', default='node')
args = parser.parse_args()
if platform.system() != 'Darwin' or platform.machine() != 'arm64':
    raise SystemExit('Requires an ARM64 Mac with clang.')
raw = Path('input/global/apks/2026-09-22-v1.0.1-25/libil2cpp.so')
sha = '514a5b73d038c264b60cc91fd4a747cf178190c6b2096e6d7007c2020e2b1bca'
if hashlib.sha256(raw.read_bytes()).hexdigest() != sha:
    raise SystemExit('Audited client SHA mismatch.')
args.output.mkdir(parents=True, exist_ok=True)
memory = ElfMemory(Path('input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/libil2cpp.decoded.so'))
instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(memory.read(0x55e5268, 0x44), 0x55e5268))
memory.close()
assembly = '.text\n.globl _client_undo\n.p2align 2\n_client_undo:\n' + '\n'.join(
    f'  {i.mnemonic} {i.op_str} // {i.address:#x}' for i in instructions) + '\n'
(args.output/'client-undo.S').write_text(assembly)
(args.output/'client-undo.c').write_text('''#include <stdio.h>
#include <stddef.h>
struct State { int power; float combo, general, just, perfect, great, good; int luck; };
_Static_assert(sizeof(struct State)==32 && offsetof(struct State,general)==8,"native layout");
extern void client_undo(struct State*, struct State*);
int main(void) { int count;
while(scanf("%d", &count)==1) {
  struct State s={.general=1}, d={0}; float value;
  for(int i=0;i<count;i++) { if(scanf("%f", &value)!=1)return 1; s.general+=value; d.general+=value; }
  float before=s.general; client_undo(&s,&d);
  printf("%a %a\\n",(double)before,(double)s.general);
}return 0;}
''')
subprocess.run(['clang', '-ffp-contract=off', str(args.output/'client-undo.c'), str(args.output/'client-undo.S'), '-o', str(args.output/'client-undo')], check=True)
f32 = lambda n: struct.unpack('<f', struct.pack('<f', n))[0]
rng = random.Random(20261002)
vectors = [[f32(.3)], [f32(.3), f32(.7)], [f32(1.3), -f32(1.3)]]
for _ in range(4093):
    vectors.append([f32(rng.randint(-100000, 100000)/100000) for _ in range(rng.randint(1, 12))])
lines = [' '.join(map(str, [len(v), *v])) for v in vectors]
native = subprocess.run([str(args.output/'client-undo')], input='\n'.join(lines), text=True, capture_output=True, check=True).stdout.splitlines()
cases = [dict(deltas=v, before=float.fromhex(n.split()[0]), after=float.fromhex(n.split()[1])) for v, n in zip(vectors, native)]
assert len(cases) == 4096
(args.output/'native-undo-vectors.json').write_text(json.dumps(cases))
verify = '''import {readFileSync,writeFileSync} from 'node:fs';
import {createScoreReplay} from './site/src/lib/scoring-rules/formal-score-replay.mjs';
const cases=JSON.parse(readFileSync(process.argv[1])), differences=[];
for(const [index,c] of cases.entries()) {
  const r=createScoreReplay({musicLengthMs:100,scoreNote:()=>({score:0})});
  for(const general of c.deltas) r.addFactor({timeMs:1,ownerId:1,general});
  r.calculate(40);const before=r.state.general;r.calculate(0);const after=r.state.general;
  if(before!==c.before||after!==c.after) differences.push({index,before,after,...c});
}
const report={vectors:cases.length,differences};
writeFileSync(process.argv[2],JSON.stringify(report,null,2));console.log(JSON.stringify(report));
process.exitCode=differences.length?1:0;'''
subprocess.run([args.node, '--input-type=module', '-e', verify, str(args.output/'native-undo-vectors.json'), str(args.output/'comparison.json')], check=True)
(args.output/'fixture.json').write_text(json.dumps(dict(nativeSha256=sha, method='ScoreFactorState.UndoDiff', address='0x55e5268', vectors=cases[:32]), indent=2)+'\n')
