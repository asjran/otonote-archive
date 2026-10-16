import test from 'node:test';
import assert from 'node:assert/strict';
import {RANKING_OPTIONS, defaultRankingDirection, rankRefinedSongRows as rank, validateRankingOptions, scopeRankingRows, rankingSongLinks} from '../src/lib/song-ranking-options.mjs';
import {withSongSkillProfile} from '../src/lib/song-skill-profile.mjs';
import {combineSongRankings} from '../src/lib/shared-song-rankings.mjs';
import {SCORE_MODEL_VERSION} from '../src/lib/scoring-rules/model-version.mjs';
const row = (id, patch = {}) => ({id, trackId:`global--${id}`, sourceEdition:'global', title:id, bands:['band-1'], bandLabels:['MyGO!!!!!'], difficulty:'expert', level:25,
  attribute:'Cool', expectedScore:1000, minimumScore:800, maximumScore:1200, p10Score:850, baseScore:700, skillScoreGain:300, chartSeconds:100, audioSeconds:120,
  benchmark:{power:100000}, applicableEditions:['global'], pendingEditions:[], meta:{averageDensity:4, peakDensity:12, bpmMin:120, bpmMax:180}, ...patch});
const ids = rows => rows.map(r => r.id);

test('minimum, maximum, P10, skill gain and density each order by their own values', () => {
  const a = row('a'), b = row('b',{minimumScore:900, maximumScore:1100, p10Score:950, skillScoreGain:200,meta:{averageDensity:5}});
  assert.deepEqual(ids(rank([a,b],{metric:'minimumScore'})),['b','a']);
  assert.deepEqual(ids(rank([a,b],{metric:'maximumScore'})),['a','b']);
  assert.deepEqual(ids(rank([a,b],{metric:'p10Score'})),['b','a']);
  assert.deepEqual(ids(rank([a,b],{metric:'skillScoreGain'})),['a','b']);
  assert.deepEqual(ids(rank([a,b],{metric:'averageDensity'})),['b','a']);
});
test('every selectable metric accepts both directions; missing values stay last with no rank', () => {
  for (const metric of Object.keys(RANKING_OPTIONS).filter(key => key !== 'requiredPower')) {
    const rows = [row('a'),row('b',{expectedScore:1100}),row('missing',{expectedScore:null, minimumScore:null, maximumScore:null, p10Score:null,skillScoreGain:null,meta:null})];
    for (const direction of ['asc','desc']) {
      const result = rank(rows,{metric,direction});
      const valid = result.filter(r => r.rank !== null);
      for(let i=1;i<valid.length;i++) assert.ok(direction === 'asc' ? valid[i-1][metric] <= valid[i][metric] : valid[i-1][metric] >= valid[i][metric],metric);
      assert.ok(result.slice(valid.length).every(r => r.rank === null));
    }
  }
  assert.equal(defaultRankingDirection('durationSeconds'),'asc');
});
test('raw ties use competition ranks and stable IDs in either direction', () => {
  const rows = [row('b'),row('a'),row('c',{expectedScore:999.999}),row('x',{expectedScore:null})];
  assert.deepEqual(rank(rows).map(r => [r.id,r.rank]),[['a',1],['b',1],['c',3],['x',null]]);
  assert.deepEqual(rank(rows,{direction:'asc'}).map(r => [r.id,r.rank]),[['c',1],['a',2],['b',2],['x',null]]);
});
test('filters compose across query, multiple difficulties/bands, attribute, level, time, BPM and density', () => {
  const rows = [row('A Song'),row('b',{level:30}),row('c',{attribute:'Happy'}),row('d',{chartSeconds:200}),row('e',{meta:{averageDensity:2,bpmMin:120,bpmMax:180}}),row('f',{difficulty:'easy'})];
  const options = {query:'mygo',difficulty:['expert','hard'],band:['band-1','band-2'],attribute:'Cool',minLevel:24,maxLevel:26,minSeconds:90,maxSeconds:110,minBpm:100,maxBpm:200,minDensity:3,maxDensity:5};
  assert.deepEqual(ids(rank(rows,options)),['A Song']);
  assert.deepEqual(ids(rank(rows,{...options,query:'Ａ Ｓｏｎｇ'})),['A Song']);
});
test('BPM range requires the whole known tempo span, and bounded fields never match missing data', () => {
  const rows = [row('a'),row('missing',{meta:{bpmMin:null,bpmMax:null}})];
  assert.deepEqual(ids(rank(rows,{minBpm:130})),[]);
  assert.deepEqual(ids(rank(rows,{maxBpm:170})),[]);
  assert.deepEqual(ids(rank(rows,{minDensity:0})),['a']);
});
test('short songs use selected duration, overhead can reorder efficiency and missing time stays missing', () => {
  const rows=[row('a',{expectedScore:100,chartSeconds:10}),row('b',{expectedScore:150,chartSeconds:20}),row('x',{audioSeconds:null})];
  assert.deepEqual(ids(rank(rows.slice(0,2),{metric:'efficiency'})),['a','b']);
  assert.deepEqual(ids(rank(rows.slice(0,2),{metric:'efficiency',overhead:100})),['b','a']);
  assert.equal(rank(rows,{metric:'efficiency',durationBasis:'audio',overhead:100}).at(-1).rank,null);
  assert.deepEqual(ids(rank(rows,{metric:'durationSeconds',maxSeconds:15})),['a']);
  assert.deepEqual(ids(rank(rows,{maxSeconds:15,durationBasis:'audio'})),[]);
  assert.equal(rank([rows[0]],{metric:'p10Efficiency',overhead:10})[0].p10Efficiency,850/20);
});
test('filter before picking one chart per song, then rerank; do not group by title or colliding IDs', () => {
  const rows=[row('a',{songIdentity:'same',difficulty:'expert',expectedScore:1200}),row('b',{songIdentity:'same',difficulty:'hard',expectedScore:1100}),row('c',{title:'a',expectedScore:1100})];
  assert.deepEqual(rank(rows,{grouping:'songs'}).map(r=>[r.id,r.rank]),[['a',1],['c',2]]);
  assert.deepEqual(ids(rank(rows,{grouping:'songs',difficulty:'hard'})),['b']);
  assert.deepEqual(ids(rank(rows,{grouping:'songs',direction:'asc'})),['b','c']);
  assert.equal(rank([row('a'),row('jp-a',{sourceEdition:'jp',trackId:'jp--a'})],{grouping:'songs'}).length,2);
  assert.deepEqual(ids(rank(rows,{grouping:'songs',minValue:1150})),['a']);
});
test('unknown values sort after valid zero; a zero-width range accepts zero', () => {
  const rows=[row('missing',{skillScoreGain:null}),row('zero',{skillScoreGain:0})];
  assert.deepEqual(rank(rows,{metric:'skillScoreGain',direction:'asc'}).map(r=>[r.id,r.rank]),[['zero',1],['missing',null]]);
  assert.deepEqual(ids(rank(rows,{metric:'skillScoreGain',minValue:0,maxValue:0})),['zero']);
});
test('ordinary skill share excludes Gekisou placement and section bonuses from its denominator', () => {
  assert.equal(rank([row('gekisou',{expectedScore:3000})],{metric:'skillShare'})[0].skillShare,0.3);
  assert.equal(rank([row('missing',{baseScore:null})],{metric:'skillShare'})[0].rank,null);
});
test('invalid numeric ranges, negative overhead and unknown metrics cannot silently create a ranking', () => {
  for (const options of [{minLevel:30,maxLevel:20},{minSeconds:120,maxSeconds:90},{minDensity:5,maxDensity:1},{minBpm:200,maxBpm:100},{minValue:4,maxValue:2},{maxSeconds:'oops'},{overhead:-1},{overhead:3601},{minLevel:Infinity},{metric:'__proto__'},{direction:'sideways'}]) assert.throws(()=>rank([],options));
  assert.equal(validateRankingOptions({minLevel:'',maxLevel:'all',overhead:''}).overhead,0);
});
test('edition selection retains pending rows but clears borrowed scores, windows and replay inputs', () => {
  const rows=[row('merged',{applicableEditions:['jp'],pendingEditions:['global'],replaySource:{releaseId:'jp'},skillReference:{version:'test'}}),row('global'),row('jp',{applicableEditions:['jp']})];
  const selected=scopeRankingRows(rows,'global');
  assert.deepEqual(ids(selected),['merged','global']);
  assert.equal(selected[0].pending,true); assert.equal(selected[0].expectedScore,null); assert.equal(selected[0].baseScore,null);
  assert.equal(selected[0].minimumScore,null); assert.equal(selected[0].replaySource,null); assert.equal(selected[0].skillReference,null);
  assert.equal(withSongSkillProfile(selected[0],Array.from({length:5},()=>({percent:0,seconds:0}))).expectedScore,null);
  assert.deepEqual(ids(rank(selected,{status:'pending'})),['merged']);
  assert.deepEqual(ids(rank(selected,{status:'calculated'})),['global']);
  assert.deepEqual(ids(rank([row('missing',{expectedScore:null})],{status:'unavailable'})),['missing']);
  assert.equal(rows[0].expectedScore,1000,'source is immutable');
});
test('pending edition filters use that edition level and duration, and links do not require grade thresholds', () => {
  const shared=row('merged',{sourceEdition:'jp',trackId:'jp--song-j',applicableEditions:['jp'],pendingEditions:['global'],
    editionChartReferences:{global:{trackId:'song-g',sourceReleaseId:'global-release',title:'Global title',level:30,chartSeconds:150,audioSeconds:160}}});
  const scoped=scopeRankingRows([shared],'global')[0];
  assert.equal(scoped.level,30);assert.equal(scoped.chartSeconds,150);assert.equal(scoped.title,'Global title');
  assert.equal(scoped.meta,null);assert.equal(scoped.expectedScore,null);
  assert.equal(rank([shared],{edition:'global',minLevel:28,maxSeconds:120}).length,0);
  assert.equal(rank([shared],{edition:'global',minLevel:28,metric:'durationSeconds'})[0].durationSeconds,150);
  assert.match(rankingSongLinks(shared,{edition:'global'}).calculator,/\/global\/zh-CN\/tools\/song-calculator\/\?song=song-g/);
});
test('grade ranking binds the selected edition thresholds and never lends an unverified score', () => {
  const thresholds=offset=>Array.from({length:6},(_,i)=>({rank:i+2,score:i*offset}));
  const refs={global:{edition:'global',verified:true,trackId:'g',thresholds:thresholds(100)},jp:{edition:'jp',verified:true,trackId:'j',thresholds:thresholds(200)}};
  const rows=[row('a',{gradeReferences:refs}),row('unverified',{gradeReferences:{jp:{...refs.jp,verified:false}}})];
  assert.equal(rank(rows,{metric:'requiredPower',gradeEdition:'global',targetRank:5,profile:'benchmark'})[0].targetScore,300);
  const jp=rank(rows,{metric:'requiredPower',gradeEdition:'jp',targetRank:5,profile:'benchmark',score:600});
  assert.equal(jp[0].requiredPower,60000); assert.equal(jp[0].enteredRank,5);
  assert.equal(jp[1].targetScore,600); assert.equal(jp[1].rank,null);
  assert.deepEqual(ids(rank(rows,{metric:'requiredPower',gradeEdition:'global',direction:'desc',profile:'benchmark'})),['a','unverified']);
});
test('new song identity allows grouping difficulties without changing verified result merges', () => {
  const source=edition=>({edition,catalog:{release:{id:edition},assets:[],musicTracks:[{id:'song',contentIdentity:'same-song',title:'Song',bandIds:[],bandLabels:[],musicTypeLabel:'Cool'}],musicCharts:['hard','expert'].map(difficulty=>({id:difficulty,trackId:'song',difficulty,level:20,contentIdentity:difficulty}))},data:{sourceReleaseId:edition,rulesFingerprint:'same',benchmark:{power:100000,modelVersion:SCORE_MODEL_VERSION},ordinary:['hard','expert'].map((id,i)=>({id,chartFingerprint:id,expectedScore:100+i,chartSeconds:10})),gekisou:[]}});
  const rows=combineSongRankings([source('global'),source('jp')]).ordinary;
  assert.equal(rows.length,2); assert.equal(rows[0].songIdentity,rows[1].songIdentity);
  assert.equal(rank(rows,{grouping:'songs'}).length,1); assert.equal(rows[0].attribute,'Cool');
});
test('tool links preserve exact edition IDs, difficulty and valid server only', () => {
  const r=row('x',{trackId:'jp--music-99',sourceEdition:'jp',difficulty:'hard',gradeReferences:{global:{trackId:'music-20'}}});
  const links=rankingSongLinks(r,{edition:'global',locale:'en',server:'global-hmt'});
  assert.match(links.calculator,/^\/global\/en\/tools\/song-calculator\/\?song=music-20&difficulty=hard&server=global-hmt&scoreMode=ordinary$/);
  assert.match(links.chart,/music\/music-20\/\?view=analysis&difficulty=hard&server=global-hmt/);
  assert.ok(!rankingSongLinks(r,{server:'global-hmt'}).calculator.includes('server='));
  assert.ok(!rankingSongLinks(r,{edition:'global',server:'global-unknown'}).calculator.includes('server='));
  assert.match(rankingSongLinks(r,{edition:'global',server:'jp'}).event,/eventMode=ordinary/);
  assert.match(rankingSongLinks(r,{mode:'gekisou'}).calculator,/scoreMode=gekisou$/);
});
