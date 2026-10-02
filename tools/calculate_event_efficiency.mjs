// Local, reproducible calculation. Does not update production projections.
import { readFileSync, writeFileSync } from 'node:fs';
import { createEventEfficiency, eventFarmingCycle } from '../packages/scoring/scoring-rules/event-efficiency.mjs';
import { createFormationCalculator } from '../packages/scoring/scoring-rules/formation-power.mjs';
import { createFormalSongCalculator } from '../packages/scoring/scoring-rules/formal-song-score.mjs';
import { maximumPairing } from '../packages/scoring/scoring-rules/maximum-pairing.mjs';

const data = JSON.parse(readFileSync(process.argv[2]));
const target = process.argv[3];
if (!target) throw new Error('Usage: node tools/calculate_event_efficiency.mjs INPUT OUTPUT');
const { rules, tables, sourceReleaseId, names } = data;
const model = createEventEfficiency({ tables, sourceReleaseId, eventId: 1 });
const normalPower = createFormationCalculator(rules);
const adapters = [model.challengeAdapter(rules)];
const challengePower = createFormationCalculator(rules, { eventAdapters: adapters });
const title = (row, kind) => kind === 'music' ? names[row._titleTextID]
  : `${names[row._nameTextID]} · ${names[row._subtitleTextID ?? row._descriptionTextID]}`;
const permutations = xs => xs.length ? xs.flatMap((x, i) => permutations(xs.filter((_, j) => j !== i)).map(t => [x, ...t])) : [[]];
const combinations = (xs, n) => !n ? [[]] : xs.flatMap((x, i) => combinations(xs.slice(i + 1), n - 1).map(t => [x, ...t]));
const rankLabel = rank => ({ 2: 'D', 3: 'C', 4: 'B', 5: 'A', 6: 'S', 7: 'SS' })[rank];
const output = { sourceReleaseId, inputHashes: data.inputHashes, status: 'reference_model_estimate',
  assumptions: ['All cards in this JP Master; not a player inventory.',
    'Member training/level and member skills maximum; compare card rank 1 and 5.',
    'Character rank/TGW 1; memory/instruments 0; all perfect/full life/no assist.',
    'Song time uses decoded audio duration or the latest chart endpoint for that song, whichever is later; loading/menus/matchmaking excluded.',
    'Max reward bonus is exact for this pool. Candidate score search is not exhaustive.',
    'Normal/gekisou challenge points do not receive card event bonuses.',
    'Gekisou rewards are conditional on room score rank, not a forecast of random matchmaking.',
    'Badge payout rounding remains a client-model estimate, without server settlement validation.'], profiles: [] };

for (const rank of [1, 5]) {
  const growth = {};
  const memberCandidates = tables.MemberCard.map(card => {
    const g = normalPower.resolveGrowth(card, 'Member', { rank, awake: 5 });
    growth[`member-card-${card._id}`] = { rank, awake: 5, level: g.level, skillLevel: 5, gekisouSkillLevel: 5 };
    return { ...model.cardBonus('member', card._id, rank), name: title(card, 'member'), power: g.values.reduce((a, b) => a + b, 0) };
  });
  const supports = tables.SupportCard.map(card => {
    const g = normalPower.resolveGrowth(card, 'Support', { rank });
    growth[`support-card-${card._id}`] = { rank, level: g.level };
    return { ...model.cardBonus('support', card._id, rank), name: title(card, 'support'), power: g.values.reduce((a, b) => a + b, 0) };
  }).sort((a, b) => b.rewardBP - a.rewardBP || b.power - a.power);
  const byCharacter = new Map();
  for (const m of memberCandidates.sort((a, b) => b.eventPointBP - a.eventPointBP || b.power - a.power)) {
    if (!byCharacter.has(m.characterIds[0])) byCharacter.set(m.characterIds[0], m);
  }
  const members = [...byCharacter.values()].sort((a, b) => b.eventPointBP - a.eventPointBP || b.power - a.power).slice(0, 5);
  const cutoff = supports[4].rewardBP, fixed = supports.filter(s => s.rewardBP > cutoff), tied = supports.filter(s => s.rewardBP === cutoff);
  const supportSets = combinations(tied, 5 - fixed.length).map(xs => [...fixed, ...xs]);
  const maxBonusBP = members.reduce((n, m) => n + m.rewardBP, 0) + supportSets[0].reduce((n, s) => n + s.rewardBP, 0);
  const maxPointBonusBP = members.reduce((n,m)=>n+m.eventPointBP,0);
  const powerCache = new Map();
  let challengeValuePerCP = 0;
  function candidates(song, challenge) {
    const context = challenge ? tables.ChallengeMusic.find(c => c._eventId === 1 && c._liveMusicId === song._id) : song;
    const key = JSON.stringify([challenge, context._musicType, song._bestMusicTagIDs]);
    if (powerCache.has(key)) return powerCache.get(key);
    const calculator = challenge ? challengePower : normalPower, winners = [];
    for (const set of supportSets) for (const leader of members) {
      const order = [members.filter(m => m !== leader)[0], members.filter(m => m !== leader)[1], leader,
        members.filter(m => m !== leader)[2], members.filter(m => m !== leader)[3]];
      let best;
      for (const perm of permutations(set)) {
        const slots = order.map((m, i) => ({ memberCardId: `member-card-${m.id}`, supportCardId: `support-card-${perm[i].id}` }));
        const draft = { slots, selectedSongId: `music-${song._id}`, modifiers: { growth,
          ...(challenge ? { event: { id: 1, sourceReleaseId } } : {}) } };
        const power = calculator.calculate(draft).total.total;
        if (!best || power > best.power) best = { slots, power };
      }
      winners.push(best);
    }
    // Add six power/bonus tradeoff directions across ALL cards, with exact
    // character-capacity matching for each fixed leader. These are candidate
    // generators, not an exhaustive score/reward optimizer.
    const empty = () => Array.from({ length: 5 }, () => ({ memberCardId: null, supportCardId: null }));
    const draft = { selectedSongId: `music-${song._id}`, modifiers: { growth,
      ...(challenge ? { event: { id: 1, sourceReleaseId } } : {}) } };
    const pairs = [];
    for (const m of memberCandidates) for (const s of supports) {
      const slots = empty(); slots[0] = { memberCardId: `member-card-${m.id}`, supportCardId: `support-card-${s.id}` };
      pairs.push({ key: `${m.id}|${s.id}`, member: m.id, support: s.id, character: m.characterIds[0],
        rewardBP: m.rewardBP + s.rewardBP, weight: calculator.calculate({ ...draft, slots }).slots[0].total.total });
    }
    const directions = new Map([0, 5, 15, 30, 60, 120].map(lambda => [lambda, null]));
    for (const leader of memberCandidates) {
      const bonuses = new Map();
      for (const m of memberCandidates.filter(m => m.id === leader.id || m.characterIds[0] !== leader.characterIds[0])) {
        const slots = empty(); slots[2].memberCardId = `member-card-${leader.id}`;
        const index = m.id === leader.id ? 2 : 0; slots[index].memberCardId = `member-card-${m.id}`;
        bonuses.set(m.id, calculator.calculate({ ...draft, slots }).slots[index].breakdown.leader.total);
      }
      const edges = pairs.filter(p => bonuses.has(p.member)).map(p => ({ ...p, weight: p.weight + bonuses.get(p.member) }));
      for (const [lambda, previous] of directions) {
        const solution = maximumPairing({ edges: edges.map(e => ({ ...e, weight: e.weight + lambda * e.rewardBP })), requiredMembers: [leader.id] });
        if (previous && previous.value >= solution.weight) continue;
        const captain = solution.edges.find(e => e.member === leader.id), others = solution.edges.filter(e => e !== captain);
        const order = [others[0], others[1], captain, others[2], others[3]];
        directions.set(lambda, { value: solution.weight, slots: order.map(e => ({ memberCardId: `member-card-${e.member}`, supportCardId: `support-card-${e.support}` })) });
      }
    }
    winners.push(...directions.values());
    console.log(`Rank ${rank}: ${challenge ? 'challenge' : 'normal'} pairing context ${key} checked`);
    powerCache.set(key, winners);
    return winners;
  }
  const scoreCache = new Map();
  function evaluate(chart, challenge, full = false, objective = 'badges') {
    const songId = Number(chart.trackId.split('-').at(-1));
    const song = tables.LiveMusic.find(s => s._id === songId);
    const cacheKey = `${chart.id}:${challenge}`;
    let choices = scoreCache.get(cacheKey);
    if (!choices) {
      const calculator = createFormalSongCalculator(rules, chart, { eventAdapters: challenge ? adapters : [], scorePrecision: 'screen' });
      choices = candidates(song, challenge).map(c => {
      const draft = { slots: c.slots, selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty,
        modifiers: { growth, ...(challenge ? { event: { id: 1, sourceReleaseId } } : {}) } };
      const {rewardBP,eventPointBP} = model.teamBonus(c.slots.map(s => ({ memberId: Number(s.memberCardId.split('-').at(-1)), supportId: Number(s.supportCardId.split('-').at(-1)), memberRank: rank, supportRank: rank })));
      return { draft, rewardBP, eventPointBP, score: calculator.calculate(draft) };
      });
      scoreCache.set(cacheKey, choices);
    }
    const reward = c => model.rewards({ mode: challenge ? 'challenge' : 'ordinary', scoreRank: model.scoreRank(songId, c.score.minimumScore), rewardBP: c.rewardBP, eventPointBP: c.eventPointBP, liveBoost: challenge ? 0 : 1 });
    const value = c => {
      const r = reward(c);
      return challenge ? r.badges : objective === 'cp' ? r.challengePoints : r.badges + r.challengePoints * challengeValuePerCP;
    };
    const compare = (a, b) => value(b) - value(a) || reward(b).badges - reward(a).badges || b.score.minimumScore - a.score.minimumScore;
    choices.sort(compare);
    let best = choices[0];
    if (full) {
      const final = createFormalSongCalculator(rules, chart, { eventAdapters: challenge ? adapters : [] });
      best = choices.slice(0, 3).map(c => ({ ...c, score: final.calculate(c.draft) })).sort(compare)[0];
    }
    const scoreRank = model.scoreRank(songId, best.score.minimumScore);
    const rewards = model.rewards({ mode: challenge ? 'challenge' : 'ordinary', scoreRank, rewardBP: best.rewardBP, eventPointBP: best.eventPointBP, liveBoost: challenge ? 0 : 1 });
    const duration = Math.max(chart.audioDuration, ...data.charts.filter(c => c.trackId === chart.trackId).map(c => c.duration));
    return { songId, name: title(song, 'music'), chartId: chart.id, difficulty: chart.difficulty,
      level: best.score.chart.level, duration, objective, scorePrecision: best.score.scorePrecision,
      orderCount: best.score.orderCount, minimumScore: best.score.minimumScore, expectedScore: best.score.expectedScore,
      maximumScore: best.score.maximumScore, power: best.score.power, scoreRank, rank: rankLabel(scoreRank),
      rewardBP: best.rewardBP, eventPointBP: best.eventPointBP, rewards, badgesPerMinute: rewards.badges * 60 / duration,
      challengePointsPerMinute: rewards.challengePoints * 60 / duration,
      effectiveBadges: challenge ? rewards.badges : rewards.badges + rewards.challengePoints * challengeValuePerCP,
      ssThreshold: tables.LiveScoreRank.find(r => r._group === song._liveScoreRankGroup && r._liveScoreRank === 7)._requiredScore,
      slots: best.draft.slots.map(s => {
        const m = memberCandidates.find(c => `member-card-${c.id}` === s.memberCardId), p = supports.find(c => `support-card-${c.id}` === s.supportCardId);
        return { ...s, member: m.name, support: p.name, memberBonus: m.eventPointBP / 100, supportBonus: p.rewardBP / 100 };
      }) };
  }
  const challengeIds = new Set(tables.ChallengeMusic.filter(r => r._eventId === 1).map(r => r._liveMusicId));
  const challenges = data.charts.filter(c => challengeIds.has(Number(c.trackId.split('-').at(-1)))).map(c => evaluate(c, true, true));
  challenges.sort((a, b) => b.rewards.badgesPerChallengePoint - a.rewards.badgesPerChallengePoint || b.badgesPerMinute - a.badgesPerMinute);
  challengeValuePerCP = challenges[0].rewards.badgesPerChallengePoint;
  console.log(`Rank ${rank}: challenge charts checked (${challenges.length}); bonus +${maxBonusBP / 100}%`);
  const normal = [], cpNormal = [];
  for (const [i, chart] of data.charts.entries()) {
    normal.push(evaluate(chart, false));
    cpNormal.push(evaluate(chart, false, false, 'cp'));
    if (i % 40 === 39) console.log(`Rank ${rank}: normal screening ${i + 1}/${data.charts.length}`);
  }
  // Full re-evaluation is required before a recommendation is reported.
  const byEfficiency = (a, b) => b.effectiveBadges / (b.duration + b.rewards.challengePoints / 1600 * challenges[0].duration)
    - a.effectiveBadges / (a.duration + a.rewards.challengePoints / 1600 * challenges[0].duration);
  normal.sort(byEfficiency);
  cpNormal.sort((a, b) => b.challengePointsPerMinute - a.challengePointsPerMinute || b.badgesPerMinute - a.badgesPerMinute);
  const shortlist = [...new Map([...normal.slice(0, 12), ...[...normal].sort((a, b) => b.effectiveBadges - a.effectiveBadges).slice(0, 12)]
    .map(c => [c.chartId, c])).values()];
  const finals = shortlist.map(c => evaluate(data.charts.find(x => x.id === c.chartId), false, true));
  finals.sort(byEfficiency);
  const cpFinals = cpNormal.slice(0, 12).map(c => evaluate(data.charts.find(x => x.id === c.chartId), false, true, 'cp'))
    .sort((a, b) => b.challengePointsPerMinute - a.challengePointsPerMinute || b.badgesPerMinute - a.badgesPerMinute);
  challenges.sort((a, b) => b.rewards.badgesPerChallengePoint - a.rewards.badgesPerChallengePoint || b.badgesPerMinute - a.badgesPerMinute);
  const bestNormal = finals[0], bestChallenge = challenges[0];
  const perBoost = [1, 2, 3, 5, 10].map(liveBoost => model.rewards({ mode: 'ordinary', scoreRank: bestNormal.scoreRank, rewardBP: bestNormal.rewardBP, eventPointBP: bestNormal.eventPointBP, liveBoost }));
  const challengeCosts = [200, 400, 800, 1600].map(challengeCost => model.rewards({ mode: 'challenge', scoreRank: bestChallenge.scoreRank, rewardBP: bestChallenge.rewardBP, eventPointBP: bestChallenge.eventPointBP, challengeCost }));
  const cycles = [200, 400, 800, 1600].map(challengeCost => ({ challengeCost, ...eventFarmingCycle({
    normal: model.rewards({ mode: 'ordinary', scoreRank: bestNormal.scoreRank, rewardBP: bestNormal.rewardBP, eventPointBP: bestNormal.eventPointBP, liveBoost: 10 }),
    challenge: model.rewards({ mode: 'challenge', scoreRank: bestChallenge.scoreRank, rewardBP: bestChallenge.rewardBP, eventPointBP: bestChallenge.eventPointBP, challengeCost }),
    normalPlays: 10, normalSeconds: bestNormal.duration, challengeSeconds: bestChallenge.duration }) }));
  output.profiles.push({ rank, maxBonusBP, maxPointBonusBP, members, supportChoices: supports.filter(s => s.rewardBP >= cutoff),
    supportSetCount: supportSets.length, normalScreened: normal.length, normalFinals: finals, cpFinals, challenges, perBoost, challengeCosts, cycles });
  writeFileSync(target, JSON.stringify(output, null, 2) + '\n');
}
console.log(`Saved ${target}`);
