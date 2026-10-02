import test from 'node:test';
import assert from 'node:assert/strict';
import { createEventEfficiency, eventFarmingCycle, battleScoreRequirement, planChallengeSpending } from '../src/lib/scoring-rules/event-efficiency.mjs';

function fixture() {
  const effect = (id, type, target, bonus, values, extra = {}) => ({ _id: id, _eventId: 1, _resourceTypeConstraint: type,
    _memberCardId: type === 2 ? target : 0, _supportCardId: type === 3 ? target : 0,
    _eventBonusType: bonus, ...Object.fromEntries(values.map((v, i) => [`_rank${i + 1}EffectValue`, v])), ...extra });
  const tables = {
    Event: [{ _id: 1, _eventType: 1, _eventItemId: 43, _liveEventPointGroup: 1, _liveEventRewardGroup: 2, _challengeLiveEventPointGroup: 1, _challengeLiveEventRewardGroup: 2 }],
    EventEffect: [effect(1, 2, 1, 0, [1500, 1750, 2000, 2250, 2500]), effect(2, 3, 1, 1, [3000, 3500, 4000, 4500, 5000]),
      effect(3, 2, 0, 0, [2000, 2300, 2600, 2900, 3200], { _bandId: 3 }),
      effect(4, 2, 1, 2, [6000, 6000, 6000, 6000, 10000]), effect(5, 3, 1, 2, [6000, 6000, 6000, 6000, 10000])],
    Character: [1, 2, 3, 4, 5].map(_id => ({ _id, _bandID: _id === 1 ? 3 : 1 })),
    MemberCard: [1, 2, 3, 4, 5].map(_id => ({ _id, _characterID: _id, _cardType: 2 })),
    SupportCard: [1, 2, 3, 4, 5].map(_id => ({ _id, _characterIDs: [_id], _cardType: 2 })),
    LiveMusic: [{ _id: 100, _liveScoreRankGroup: 3, _musicType: 1 }],
    LiveScoreRank: [2, 3, 4, 5, 6, 7].map((r, i) => ({ _group: 3, _liveScoreRank: r, _requiredScore: i * 1000, _battleLiveRequiredScore: i * 2000 })),
    ChallengeMusic: [{ _eventId: 1, _liveMusicId: 100, _musicType: 2, _gekisouMission1: 0, _gekisouMission2: 0, _gekisouMission3: 0 }],
    LiveMusicBoostBonus: [1, 2, 10].map(n => ({ _consumedLiveBoostCount: n, _eventPointRate: n * 5, _liveMusicRewardRate: n * 5 })),
    ChallengeMusicBoostBonus: [200, 400, 800, 1600].map(n => ({ _consumedChallengePointCount: n, _eventPointRate: n / 200, _liveMusicRewardRate: n / 200 })),
    LiveChallengePoint: [{ _scoreRank: 7, _value: 10 }], LiveEventPoint: [{ _group: 1, _scoreRank: 7, _value: 100 }],
    ChallengeLiveEventPoint: [{ _group: 1, _scoreRank: 7, _value: 5000 }],
    LiveEventReward: [{ _eventGroup: 2, _group: 99, _scoreRank: 7, _resourceType: 1, _resourceId: 43, _resourceCount: 120, _probability: 10000 }],
    ChallengeLiveEventReward: [{ _eventGroup: 2, _group: 99, _scoreRank: 7, _resourceType: 1, _resourceId: 43, _resourceCount: 4950, _probability: 10000 }]
  };
  return { tables, sourceReleaseId: 'jp-test', eventId: 1 };
}
test('point, item and power effects stay separate while matching conditions stack', () => {
  const model = createEventEfficiency(fixture());
  assert.equal(model.cardBonus('member', 1, 2).eventPointBP, 4050);
  assert.equal(model.cardBonus('member', 1, 2).rewardBP, 0);
  assert.equal(model.cardBonus('support', 1, 2).eventPointBP, 0);
  assert.equal(model.cardBonus('support', 1, 2).rewardBP, 3500);
  assert.equal(model.cardBonus('member', 1, 2).powerBP, 6000);
  const slots = [1, 2, 3, 4, 5].map(id => ({ memberId: id, supportId: id, memberRank: 2, supportRank: 2 }));
  assert.equal(model.teamBonus(slots).rewardBP, 3500);
  assert.equal(model.teamBonus(slots).eventPointBP, 4050);
  slots[4].memberId = 1; assert.throws(() => model.teamBonus(slots), /Duplicate/);
});
test('C rank one fire settlement uses item 272 percent and point 172 percent independently',()=>{
 const input=fixture();
 input.tables.LiveEventPoint.push({_group:1,_scoreRank:3,_value:25});
 input.tables.LiveEventReward.push({_eventGroup:2,_scoreRank:3,_resourceType:1,_resourceId:43,_resourceCount:30,_probability:10000});
 input.tables.LiveChallengePoint.push({_scoreRank:3,_value:4});
 const model=createEventEfficiency(input);
 for(const mode of ['ordinary','gekisou']){
  const result=model.rewards({mode,scoreRank:3,liveBoost:1,rewardBP:27200,eventPointBP:17200});
  assert.equal(result.badges,558);assert.equal(result.eventPoints,340);assert.equal(result.challengePoints,20);
 }
 assert.throws(()=>model.rewards({mode:'ordinary',scoreRank:3,liveBoost:1,rewardBP:27200}),/point bonus/);
});
test('ordinary and gekisou CP ignore event bonus, rewards do not', () => {
  const model = createEventEfficiency(fixture());
  for (const mode of ['ordinary', 'gekisou']) {
    const base = model.rewards({ mode, scoreRank: 7, rewardBP: 0, eventPointBP: 0, liveBoost: 1 });
    const bonus = model.rewards({ mode, scoreRank: 7, rewardBP: 30000, eventPointBP: 30000, liveBoost: 1 });
    assert.equal(base.challengePoints, 50); assert.equal(bonus.challengePoints, 50);
    assert.equal(bonus.eventPoints, 2000); assert.equal(bonus.badges, 2400);
    assert.equal(model.rewards({ mode, scoreRank: 7, rewardBP: 0, eventPointBP: 0 }).challengePointsPerBoost, null);
  }
});
test('challenge costs scale rewards, never produce CP or spend live boost', () => {
  const model = createEventEfficiency(fixture());
  for (const challengeCost of [200, 400, 800, 1600]) {
    const r = model.rewards({ mode: 'challenge', scoreRank: 7, rewardBP: 30000, eventPointBP: 30000, challengeCost });
    assert.equal(r.badges, 19800 * challengeCost / 200); assert.equal(r.eventPoints, 20000 * challengeCost / 200);
    assert.equal(r.badgesPerChallengePoint, 99); assert.equal(r.challengePoints, 0);
  }
  assert.throws(() => model.rewards({ mode: 'challenge', scoreRank: 7, rewardBP: 0, eventPointBP: 0, liveBoost: 1 }));
  assert.throws(() => model.rewards({ mode: 'challenge', scoreRank: 7, rewardBP: 0, eventPointBP: 0, challengeCost: 201 }));
});
test('threshold boundary, own power rounding, additive support BP and song override', () => {
  const input = fixture(), model = createEventEfficiency(input);
  assert.equal(model.scoreRank(100, 4999), 6); assert.equal(model.scoreRank(100, 5000), 7);
  const adapter = model.challengeAdapter({ sourceReleaseId: input.sourceReleaseId, tables: input.tables });
  const ctx = { draft: {}, member: { _id: 1 }, support: { _id: 1 } };
  assert.deepEqual(adapter.handlers.member_power([42653, 33719, 34872], [], ctx), [68244, 53950, 55795]);
  assert.deepEqual(adapter.handlers.support_power([600, 500, 400], [], ctx), [6600, 6500, 6400]);
  assert.equal(adapter.handlers.song_context(input.tables.LiveMusic[0])._musicType, 2);
  assert.throws(() => adapter.handlers.song_context({ _id: 999 }));
  assert.throws(() => model.challengeAdapter({ sourceReleaseId: 'jp-other', tables: input.tables }));
});
test('finite farming keeps leftover CP, includes both stages and full cycle time', () => {
  const model = createEventEfficiency(fixture());
  const normal = model.rewards({ mode: 'ordinary', scoreRank: 7, rewardBP: 0, eventPointBP: 0, liveBoost: 1 });
  const challenge = model.rewards({ mode: 'challenge', scoreRank: 7, rewardBP: 30000, eventPointBP: 30000 });
  const cycle = eventFarmingCycle({ normal, challenge, normalPlays: 5, normalSeconds: 120, challengeSeconds: 100 });
  assert.equal(cycle.challengePlays, 1); assert.equal(cycle.remainingCP, 50);
  assert.equal(cycle.badges, 22800); assert.equal(cycle.seconds, 700); assert.equal(cycle.badgesPerBoost, 4560);
  assert.throws(() => eventFarmingCycle({ normal, challenge: { ...challenge, eventId: 2 }, normalPlays: 5 }));
});
test('battle rank uses eligible room total and a player-count-dependent threshold', () => {
  assert.equal(battleScoreRequirement(10000, 5), 50000);
  assert.equal(battleScoreRequirement(10000, 1), 22360);
  assert.equal(battleScoreRequirement(10000, 2), 31622);
  assert.throws(() => battleScoreRequirement(10000, 0));
  const model = createEventEfficiency(fixture());
  assert.equal(model.battleRank(100, 49999, 5), 6);
  assert.equal(model.battleRank(100, 50000, 5), 7);
});
test('missing and unsupported data fails closed instead of becoming zero reward', () => {
  const input = fixture(); input.tables.EventEffect[0]._tagId = 1;
  assert.throws(() => createEventEfficiency(input), /Unsupported/);
  const model = createEventEfficiency(fixture());
  assert.throws(() => model.rewards({ mode: 'arena', scoreRank: 7, rewardBP: 0, eventPointBP: 0 }));
  assert.throws(() => model.rewards({ mode: 'ordinary', scoreRank: 6, rewardBP: 0, eventPointBP: 0 }), /Missing/);
  assert.throws(() => model.cardBonus('member', 1, 0));
});
test('mixed challenge tiers spend the remainder and minimize plays at equal yield', () => {
  const model = createEventEfficiency(fixture());
  const options = [200, 400, 800, 1600].map(challengeCost => model.rewards({ mode: 'challenge', scoreRank: 7, rewardBP: 0, eventPointBP: 0, challengeCost }));
  const plan = planChallengeSpending(options, 3000);
  assert.equal(plan.badges, 74250); assert.equal(plan.remainingCP, 0); assert.equal(plan.plays, 4);
  assert.deepEqual(plan.consumption, [{ cost: 1600, plays: 1 }, { cost: 800, plays: 1 }, { cost: 400, plays: 1 }, { cost: 200, plays: 1 }]);
  const other = planChallengeSpending(options, 5050);
  assert.equal(other.plays, 4); assert.equal(other.remainingCP, 50);
  assert.deepEqual(other.consumption, [{ cost: 1600, plays: 3 }, { cost: 200, plays: 1 }]);
  assert.equal(planChallengeSpending(options, 199).badges, 0);
  assert.throws(() => planChallengeSpending([...options, { ...options[0], eventId: 2 }], 1000));
});
