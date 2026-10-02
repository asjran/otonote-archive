"""Run the client's scalar ARM64 score instructions on this ARM64 Mac.

Only the arithmetic leaf is executed. Unity objects, tables, life selection and
skill scheduling are supplied as explicit inputs, not claimed as emulated.
"""
import argparse, hashlib, json, platform, random, subprocess, sys
from pathlib import Path
sys.path[:0] = ['analysis', 'analysis/vendor']
from crypto.inspect_il2cpp import ElfMemory
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--node', default='node')
args = parser.parse_args()
if platform.system() != 'Darwin' or platform.machine() != 'arm64':
    raise SystemExit('This verification harness requires an ARM64 Mac with clang.')
out = args.output
out.mkdir(parents=True, exist_ok=True)
original = Path('input/global/apks/2026-09-22-v1.0.1-25/libil2cpp.so')
expected_sha = '514a5b73d038c264b60cc91fd4a747cf178190c6b2096e6d7007c2020e2b1bca'
if hashlib.sha256(original.read_bytes()).hexdigest() != expected_sha:
    raise SystemExit('Client binary does not match the audited release.')
memory = ElfMemory(Path('input/global/decrypted/2026-09-22-v1.0.1-25/il2cpp/libil2cpp.decoded.so'))
instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(memory.read(0x55e5018, 0x55e50c4 - 0x55e5018), 0x55e5018))
memory.close()
body = '\n'.join(f'  {i.mnemonic} {i.op_str} // client {i.address:#x}' for i in instructions if i.mnemonic not in ('ldr', 'ldp'))
assembly = '''.text
.globl _client_score
.p2align 2
_client_score:
  stp x19, x20, [sp, #-128]!
  stp x21, x22, [sp, #16]
  stp x23, x24, [sp, #32]
  str x25, [sp, #48]
  stp d8, d9, [sp, #64]
  stp d10, d11, [sp, #80]
  stp d12, d13, [sp, #96]
  str d14, [sp, #112]
  ldr w25, [x0]
  ldr s10, [x0, #4]
  ldr s11, [x0, #8]
  ldr w23, [x0, #12]
  ldr w22, [x0, #16]
  ldr s9, [x0, #20]
  ldr s8, [x0, #24]
  ldr w19, [x0, #28]
  ldr w24, [x0, #32]
  ldr s14, [x0, #36]
  ldr s12, [x0, #40]
  ldr s13, [x0, #44]
''' + body + '''
  ldp x19, x20, [sp]
  ldp x21, x22, [sp, #16]
  ldp x23, x24, [sp, #32]
  ldr x25, [sp, #48]
  ldp d8, d9, [sp, #64]
  ldp d10, d11, [sp, #80]
  ldp d12, d13, [sp, #96]
  ldr d14, [sp, #112]
  add sp, sp, #128
  ret
'''
(out / 'client-core.S').write_text(assembly)
(out / 'client-core.c').write_text('''#include <stdio.h>
struct Params {int power; float adjustment, level; int note, judge; float combo, skill; int luck, count; float event, life, assist;};
extern int client_score(struct Params*);
int main(void) {struct Params p;
while(scanf("%d %f %f %d %d %f %f %d %d %f %f %f", &p.power,&p.adjustment,&p.level,&p.note,&p.judge,&p.combo,&p.skill,&p.luck,&p.count,&p.event,&p.life,&p.assist)==12) printf("%d\\n",client_score(&p));
return 0;}
''')
subprocess.run(['clang', str(out/'client-core.c'), str(out/'client-core.S'), '-o', str(out/'client-core')], check=True)
rng=random.Random(20261002)
cases=[]
for i in range(4096):
    p=dict(totalPower=rng.choice([1, 99999, 100000, 1118790, 16777217, rng.randrange(1, 3000000)]),
      scoreAdjustmentFactor=rng.choice([1,3]),musicScoreLevelFactor=rng.choice([1,1.105,1.15]),
      noteFactorPercent=rng.choice([0,10,20,50,100,200]),judgementFactorPercent=rng.choice([0,50,80,100,101]),
      comboBonusFactor=rng.choice([1,1.1,1.2,2,4]),scoreUpFactor=rng.choice([0.9999999403953552,1,1.3,2.299990177154541,4.5]),
      luckScoreFactorPercent=rng.choice([100,110,200]),convertedNoteCount=rng.choice([3,525,555,1024]),
      eventBonusFactor=rng.choice([1,1.1,1.3333,2.25]),lifeOnusFactor=rng.choice([0.3,0.5]),
      assistModeNoteScoreFactor=rng.choice([1,0.5,0.8]),currentLife=rng.choice([0,1,1000]))
    cases.append(p)
keys=['totalPower','scoreAdjustmentFactor','musicScoreLevelFactor','noteFactorPercent','judgementFactorPercent','comboBonusFactor','scoreUpFactor','luckScoreFactorPercent','convertedNoteCount','eventBonusFactor']
lines=[' '.join(map(str,[*(p[k] for k in keys),1 if p['currentLife']>0 else p['lifeOnusFactor'],p['assistModeNoteScoreFactor']])) for p in cases]
scores=list(map(int,subprocess.run([str(out/'client-core')],input='\n'.join(lines),text=True,capture_output=True,check=True).stdout.split()))
assert len(scores)==len(cases)
(out/'native-core-vectors.json').write_text(json.dumps([dict(input=p,score=s) for p,s in zip(cases,scores)]))
print(f'Executed {len(scores)} vectors with extracted client arithmetic instructions.')
verify = '''
import {readFileSync,writeFileSync} from 'node:fs';
import {calculateFormalNoteCore} from './site/src/lib/scoring-rules/formal-note-core.mjs';
const vectors=JSON.parse(readFileSync(process.argv[1]));
const differences=[];
for(const [i,v] of vectors.entries()) {
  try {const actual=calculateFormalNoteCore(v.input).score;if(actual!==v.score)differences.push({i,actual,...v});}
  catch(error){differences.push({i,error:error.message,...v});}
}
const report={vectors:vectors.length,differences};
writeFileSync(process.argv[2],JSON.stringify(report,null,2));
console.log(JSON.stringify({vectors:vectors.length,differences:differences.length}));
if(differences.length)process.exitCode=1;
'''
subprocess.run([args.node,'--input-type=module','-e',verify,str(out/'native-core-vectors.json'),str(out/'native-core-diff.json')],check=True)
