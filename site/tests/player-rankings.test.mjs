import test from 'node:test';
import assert from 'node:assert/strict';
import {validateRankingResponse, rankingStatus} from '../src/lib/player-rankings-ui.mjs';
import {eventRankingPath} from '../src/lib/event-ranking-links.mjs';
import {validateHighScoreDeck, orderedDeckSlots, rankingCard, rankingScoreAnomaly} from '../src/lib/player-ranking-decks.mjs';

test('score anomaly rule flags only the integer limit and clears on a corrected score',()=>{
  assert.equal(rankingScoreAnomaly(2147483647),'score-int32-max');
  for (const score of [0,17014421,2147483646,2147483648,'2147483647',null,undefined,NaN])
    assert.equal(rankingScoreAnomaly(score),null);
  const row={playerId:'same-player',score:2147483647};
  assert.equal(rankingScoreAnomaly(row.score),'score-int32-max');
  row.score=17014421;
  assert.equal(rankingScoreAnomaly(row.score),null);
});

const response = () => ({schemaVersion:1,serverId:'global-hmt',board:'music',eventId:'1',musicId:'100109',
  status:'available',boards:['music'],events:[{id:'1',name:'Event'}],songs:[{id:'100109',name:'Song'}],
  entries:[{playerId:'p',name:'<img onerror=alert(1)>',rank:1,score:123}],nextCursor:null,
  observedAt:'2026-09-30T00:00:00Z',expiresAt:'2026-09-30T00:15:00Z'});

test('automatic board selection accepts the collected song board but rejects foreign identities',()=>{
  const value=response();
  assert.equal(validateRankingResponse(value,'global-hmt','auto','',''),value);
  for(const args of [['global-en','auto','',''],['global-hmt','music','2',''],['global-hmt','music','1','100056']])
    assert.throws(()=>validateRankingResponse(value,...args));
});
test('malformed scores, duplicate players, timestamps and board kinds are rejected',()=>{
  for(const change of [v=>v.entries[0].score=NaN,v=>v.entries[0].rank=0,v=>v.entries.push(v.entries[0]),
    v=>v.entries=[null],v=>v.expiresAt='bad',v=>v.boards=['wrong'],v=>v.nextCursor={}]){
    const value=response();change(value);assert.throws(()=>validateRankingResponse(value,'global-hmt','auto','',''));
  }
});
test('an open page changes to stale when its observation expires',()=>{
  assert.equal(rankingStatus(response(),Date.parse('2026-09-30T00:14:59Z')),'available');
  assert.equal(rankingStatus(response(),Date.parse('2026-09-30T00:15:00Z')),'stale');
  assert.equal(rankingStatus({...response(),status:'unavailable'},Infinity),'unavailable');
});
test('event links use LiveMusic IDs and only offer configured boards',()=>{
  const event={id:1,ranking:{configured:{eventPoints:false,music:true,totalMusic:true}},challengeSongs:[{id:1,musicId:100109}]};
  assert.equal(eventRankingPath(event,'music',100109),'/rankings/?event=1&board=music&music=100109');
  assert.equal(eventRankingPath(event,'total-music'),'/rankings/?event=1&board=total-music');
  assert.equal(eventRankingPath(event,'event-points'),null);
  assert.equal(eventRankingPath(event,'music',1),null);
  assert.equal(eventRankingPath(event,'unknown'),null);
});

const deck = () => ({totalPower:2756699,cards:[{slot:0,performanceOrder:2,
  member:{masterId:59,exp:721000,rank:5,awake:4,liveSkillLevel:null,performanceSkillLevel:null},
  support:{masterId:61,exp:0,rank:5}}]});
test('high score teams accept absent optional data but reject ambiguous or unsafe slots',()=>{
  validateHighScoreDeck(null);validateHighScoreDeck(deck());
  for(const mutate of [d=>d.cards.push(d.cards[0]),d=>d.cards[0].slot=5,d=>d.cards[0].performanceOrder=true,
    d=>d.totalPower=-1,d=>d.cards[0].member.masterId=0,d=>d.cards[0].member.liveSkillLevel=0]){
    const value=deck();mutate(value);assert.throws(()=>validateHighScoreDeck(value));
  }
  const value=response();value.entries[0].highScoreDeck={cards:'bad'};
  assert.throws(()=>validateRankingResponse(value,'global-hmt','auto','',''));
});
test('card kinds never collide and incomplete decks retain five explicit positions',()=>{
  const catalog={member:{59:{name:'Member'}},support:{59:{name:'Support'}}};
  assert.equal(rankingCard('member',59,catalog).name,'Member');
  assert.equal(rankingCard('support',59,catalog).name,'Support');
  assert.equal(rankingCard('support',999,catalog),undefined);
  const slots=orderedDeckSlots(deck());assert.equal(slots.length,5);
  assert.equal(slots[0].member.masterId,59);assert.equal(slots[0].performanceOrder,2);
  assert.equal(slots[1].member,null);assert.equal(slots[1].performanceOrder,null);
});
