import { readFileSync, writeFileSync } from 'node:fs';
import { advanceStopwatch, stopwatchMilliseconds, executingSkillEnd } from '../packages/scoring/scoring-rules/formal-frame-clock.mjs';

const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Usage: node tools/verify_native_scoring_timing.mjs native.json report.json');
const data = JSON.parse(readFileSync(input, 'utf8'));
const bits = value => new Uint32Array(new Float32Array([value]).buffer)[0];
const differences = [];
let fields = 0;
for (const clock of data.clocks) {
  let elapsed = 0;
  for (const row of clock.entries) {
    elapsed = advanceStopwatch(elapsed, clock.deltaSeconds);
    fields += 2;
    if (bits(elapsed) !== row.elapsedBits || stopwatchMilliseconds(elapsed) !== row.elapsedMs) {
      differences.push({ kind: 'stopwatch', frameRate: clock.frameRate, row, elapsed, elapsedMs: stopwatchMilliseconds(elapsed) });
    }
  }
}
for (const row of data.effects) {
  const finish = executingSkillEnd(row);
  fields += 3;
  if ((finish !== null) !== row.ended || (finish ?? -1) !== row.finishMs || (finish === null ? 3 : 4) !== row.state) {
    differences.push({ kind: 'effect', row, finish });
  }
}
const result = { clientSha256: data.clientSha256, stopwatchUpdates: data.stopwatchUpdates, effectCases: data.effectCases, fields, differences };
writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ ...result, differences: differences.length }));
if (differences.length) process.exitCode = 1;
