import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { advanceStopwatch, stopwatchMilliseconds, executingSkillEnd } from '../src/lib/scoring-rules/formal-frame-clock.mjs';
import { gekisouSettlementActions } from '../src/lib/scoring-rules/gekisou-score-settlement.mjs';

const timings=JSON.parse(readFileSync(new URL('./fixtures/formal-timing-native.json',import.meta.url)));
const settlements=JSON.parse(readFileSync(new URL('./fixtures/formal-settlement-native.json',import.meta.url)));
const bits=value=>new Uint32Array(new Float32Array([value]).buffer)[0];

test('stopwatch and skill expiry match intact ARM64 method captures',()=>{
  for(const clock of timings.clocks){
    let elapsed=0,frame=0;
    for(const row of clock.entries){
      while(frame++<row.frame)elapsed=advanceStopwatch(elapsed,clock.deltaSeconds);
      frame=row.frame;
      assert.equal(bits(elapsed),row.elapsedBits,`${clock.frameRate} fps frame ${row.frame}`);
      assert.equal(stopwatchMilliseconds(elapsed),row.elapsedMs);
    }
  }
  for(const row of timings.effects)assert.equal(executingSkillEnd(row),row.ended?row.finishMs:null);
});

test('multiplayer endpoint actions match the native upload-before-serialization capture',()=>{
  for(const row of settlements.vectors){
    if(row.state!==7)continue;
    const state={startMs:row.startMs,endMs:row.endMs,releaseFrame:12},calls=[];
    const fake={calculate:time=>{calls.push(time);return row.storedAfter[time===row.startMs?0:1];}};
    gekisouSettlementActions([state])[0].run(fake);
    assert.deepEqual(calls,row.queried);
    assert.equal(state.noteScore,row.storedAfter[1]-row.storedAfter[0]);
    assert.notEqual(state.noteScore,row.frozenBefore[1]-row.frozenBefore[0]);
  }
});
