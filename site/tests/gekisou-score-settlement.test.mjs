import test from 'node:test';
import assert from 'node:assert/strict';
import { replayScoreTimeline } from '../src/lib/scoring-rules/formal-score-replay.mjs';
import { gekisouSettlementActions } from '../src/lib/scoring-rules/gekisou-score-settlement.mjs';
import { gekisouTimingCombo } from '../src/lib/scoring-rules/gekisou-timing.mjs';

const scoreNote = (_note, state) => ({ score: Math.floor(state.general * 1000000) });

test('section settlement queries the shared calculator rather than summing its final note table', () => {
  const commands = [[20,86,.78],[60,128,.4],[200,270,.18]].flatMap(([start,end,rate],slot) => [
    {timeMs:start,ownerId:slot*100+1,general:Math.fround(rate)},
    {timeMs:end,ownerId:slot*100+1,general:-Math.fround(rate)}]);
  const events = [0,40,80,120,200,240,280].map(timeMs=>({timeMs}));
  const unqueried = replayScoreTimeline({events,commands,scoreNote});
  assert.equal(unqueried.notes.filter(n=>n.timeMs>0&&n.timeMs<=120).reduce((sum,n)=>sum+n.result.score,0),5359999);
  const state = {startMs:0,endMs:120,releaseFrame:10};
  const replay = replayScoreTimeline({events,commands,scoreNote,
    frameActions:gekisouSettlementActions([state],s=>Number(BigInt(s.noteScore)*370n/100n))});
  assert.deepEqual(state.scoreQuery,{frame:10,startScore:1000000,endScore:6360000});
  assert.equal(state.noteScore,5360000);
  assert.equal(state.rankingBonus,19832000);
  assert.equal(replay.score,replay.notes.reduce((sum,n)=>sum+n.result.score,0)+state.rankingBonus);
});

test('state 7 reads endpoints once, state 8 queues the award, and the next score call installs it', () => {
  const state = {startMs:0,endMs:80,releaseFrame:6}, snapshots=[];
  const actions = gekisouSettlementActions([state],s=>s.noteScore*2);
  actions.push(...[6,7,8].map(frame=>({frame,run:r=>snapshots.push(r.score)})));
  const r = replayScoreTimeline({events:[{timeMs:40}],commands:[],scoreNote,frameActions:actions});
  assert.deepEqual(snapshots,[1000000,1000000,3000000]);
  assert.equal(r.calculate(0),0);assert.equal(r.calculate(1000),3000000);
});

test('prior section medals cancel from both endpoints instead of compounding the next medal', () => {
  const states = [{startMs:0,endMs:80,releaseFrame:6},{startMs:200,endMs:280,releaseFrame:20}];
  const replay = replayScoreTimeline({events:[40,240].map(timeMs=>({timeMs})),commands:[],scoreNote,
    frameActions:gekisouSettlementActions(states,s=>s.noteScore*2)});
  assert.deepEqual(states.map(s=>s.noteScore),[1000000,1000000]);
  assert.deepEqual(states[1].scoreQuery,{frame:20,startScore:3000000,endScore:4000000});
  assert.equal(replay.score,6000000);
});

test('explicit delayed confirmation keeps the state 7 score and credits only after receipt',()=>{
  const state={startMs:0,endMs:80,releaseFrame:6},observed=[];
  const actions=gekisouSettlementActions([state],s=>s.noteScore*2,{confirmationDelayFrames:[3]});
  actions.push(...[6,7,10,11].map(frame=>({frame,run:r=>observed.push(r.score)})));
  const result=replayScoreTimeline({events:[{timeMs:40}],commands:[],scoreNote,frameActions:actions});
  assert.deepEqual(observed,[1000000,1000000,1000000,3000000]);
  assert.equal(state.scoreQuery.frame,6);assert.equal(state.confirmationFrame,10);
  assert.equal(result.score,3000000);
  assert.throws(()=>gekisouSettlementActions([state],null,{confirmationDelayFrames:[-1]}),/延迟/);
});

test('a count view cannot read future appends or an as-yet-unreceived backdated bonus', () => {
  const history = [{timeMs:0,combo:1}], length=history.length;
  history.push({timeMs:20,combo:6});
  assert.equal(gekisouTimingCombo(history,80,length),1);
  assert.equal(gekisouTimingCombo(history,80),6);
  const recounted = [{timeMs:0,combo:5},{timeMs:20,combo:10}];
  assert.equal(gekisouTimingCombo(recounted,80),10);
  assert.equal(gekisouTimingCombo(history,80,length),1);
});
