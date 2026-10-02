import { readFileSync, writeFileSync } from 'node:fs';
import { createEventEfficiency, planChallengeSpending, battleScoreRequirement } from '../packages/scoring/scoring-rules/event-efficiency.mjs';

const [inputPath, resultPath, markdownPath] = process.argv.slice(2);
if (!markdownPath) throw new Error('Usage: node tools/report_event_efficiency.mjs INPUT RESULTS REPORT.md');
const input = JSON.parse(readFileSync(inputPath)), result = JSON.parse(readFileSync(resultPath));
if (result.profiles.length !== 2 || input.sourceReleaseId !== result.sourceReleaseId) throw new Error('Incomplete or mismatched calculation');
if(result.profiles.some(p=>!Number.isInteger(p.maxPointBonusBP)))throw Error('旧结果混合了活动点数与道具加成，请重新计算。');
const model = createEventEfficiency({ ...input, eventId: 1 });
const fmt = n => Number.isInteger(n) ? n.toLocaleString('en-US') : n.toLocaleString('en-US', { maximumFractionDigits: 2 });
const stage = rank => rank === 1 ? '成员觉醒／留影突破 0 次' : '成员觉醒／留影突破 4 次';
const difficulties = { easy: 'Easy', normal: 'Normal', hard: 'Hard', expert: 'Expert' };
const lines = ['# 活动效率计算：アイの奔流 AtoZ', '', '本地计算日期：2026-09-30。未发布网站、未连接玩家账号或实机结算。', '',
  `区服与快照：\`${result.sourceReleaseId}\`。`, '',
  '## 计算条件', '',
  '- 使用本期日服 Master 的全部 63 张成员卡、64 张留影，分别比较 Rank 1 和 Rank 5；不是个人卡库。',
  '- 成员特训、等级与成员技能按满值；角色评级与 TGW 为 1，乐器／回忆为 0。',
  '- 理想 AP、满生命、无辅助。评分使用最终 120 种技能顺序中的最低估分，仍是参考模型而非实机保底。',
  '- 每档筛选 85 首歌曲的 340 张谱面；挑战曲 12 张谱面全部复算。普通演出候选先用 10 顺序筛选，推荐用 120 顺序复算。',
  '- 配队候选包含最高活动加成队，以及六种综合力／收益加成权重方向；每个方向枚举队长并做成员—留影匹配。没有穷举全部技能组合，不宣称全局最高收益。',
  '- 时间采用同区服已解码音频与该曲最晚谱面终点的较大值。匹配、加载、菜单和结算时间未知，不算入“纯演出时间”。',
  '- 徽章数量按客户端模型估算，尚未实机核对服务端取整；下表不含兑换、任务、累计积分及循环奖励。', '',
  '## 已纳入的活动规则', '',
  '- 挑战 PT = 评分基础挑战 PT × 演出倍率，不乘队伍活动收益加成。',
  '- 活动 PT／徽章 = 对应评分基础值 × (10000 + 各自对应的加成原始值) / 10000 × 对应倍率；展示百分比不参与计算。',
  '- 挑战演出的成员能力加成逐维计算并取整；留影活动能力加成直接加到留影的能力倍率上。普通、激奏不套用挑战专属综合力加成。',
  '- 挑战曲使用活动规定的歌曲属性和激奏任务覆盖值；本期三首均没有激奏区间。',
  '- 旧版混合加成的 +450%／+750% 结论已撤回；活动点数与道具分别计算。此上限本身不保证能达到 SS。', '',
  '## 计算结果', '',
  '| 养成 | 目标 | 歌曲／难度 | 评分 | 队伍加成 | 每次挑战 PT | 每次徽章 | 消耗 |',
  '| --- | --- | --- | --- | --- | ---: | ---: | --- |'];

const supplement = { sourceReleaseId: input.sourceReleaseId, profiles: [] };
for (const p of result.profiles) {
  for (const [key, goal] of [['cpFinals', '普通演出攒挑战 PT'], ['normalFinals', '普通演出＋挑战循环刷徽章'], ['challenges', '挑战演出刷徽章']]) {
    const r = p[key][0];
    if (r.scorePrecision !== 'full' || r.orderCount !== 120) throw new Error('Unverified screening result');
    lines.push(`| ${p.rank === 1 ? '0 次' : '4 次'} | ${goal} | ${r.name} / ${difficulties[r.difficulty]} | ${r.rank} | +${fmt(r.rewardBP / 100)}% | ${fmt(r.rewards.challengePoints)} | ${fmt(r.rewards.badges)} | ${key === 'challenges' ? '200 挑战 PT' : '1 演出能量'} |`);
  }
}
lines.push('', '挑战推荐曲《これはぼくたちの生存のあらすじ》纯演出时间约 93 秒。满突破档的四个难度均达到 SS 时收益相同，因此选 Easy 可降低操作要求。', '',
  '## 激奏演出的条件收益', '',
  '激奏需要使用实际房间评分，不能将自己的普通分数套入普通演出门槛。原生评级门槛为 `trunc(基础激奏门槛 × sqrt(5 / 参与评级人数) × 参与评级人数)`。', '',
  '下表假设使用最高活动加成队、消耗 1 演出能量；不预言随机房间的评分。', '',
  '| 养成 | 房间评分 | 队伍加成 | 挑战 PT | 活动 PT | 徽章 |', '| --- | --- | --- | ---: | ---: | ---: |');
for (const p of result.profiles) {
  const rows = [5, 6, 7].map(scoreRank => model.rewards({ mode: 'gekisou', scoreRank, rewardBP: p.maxBonusBP, eventPointBP: p.maxPointBonusBP, liveBoost: 1 }));
  for (const r of rows) lines.push(`| ${p.rank === 1 ? '0 次' : '4 次'} | ${{ 5: 'A', 6: 'S', 7: 'SS' }[r.scoreRank]} | +${p.maxBonusBP / 100}% | ${r.challengePoints} | ${fmt(r.eventPoints)} | ${fmt(r.badges)} |`);
  supplement.profiles.push({ rank: p.rank, gekisouConditionalRewards: rows });
}
const songTimes = new Map();
for (const c of input.charts) songTimes.set(c.trackId, Math.max(songTimes.get(c.trackId) ?? 0, c.audioDuration, c.duration));
const shortest = [...songTimes].sort((a, b) => a[1] - b[1])[0];
const shortSong = input.tables.LiveMusic.find(m => `music-${m._id}` === shortest[0]);
const ss = input.tables.LiveScoreRank.find(r => r._group === shortSong._liveScoreRankGroup && r._liveScoreRank === 7);
lines.push('', `在“同样达到目标房间评分、匹配和等待时间相同”的条件下，本次 85 首中纯演出时间最短的是《${input.names[shortSong._titleTextID]}》，约 ${fmt(shortest[1])} 秒。五名参与评级玩家的 SS 合计分数门槛为 ${fmt(battleScoreRequirement(ss._battleLiveRequiredScore, 5))}；不能据此保证最高加成队在随机房间拿 SS。`, '',
  '## 100 演出能量的有限预算', '',
  '以下以普通刷徽章推荐队每次消耗 10 能量、共 10 次、起始挑战 PT 为 0，再把可用挑战 PT 尽量花完。目标是徽章最多，同收益下挑战次数最少。', '',
  '| 养成 | 普通演出所得挑战 PT | 挑战消耗安排 | 剩余 PT | 两阶段直接徽章合计 | 纯演出分钟 |',
  '| --- | ---: | --- | ---: | ---: | ---: |');
for (const p of result.profiles) {
  const normal = p.normalFinals[0], challenge = p.challenges[0];
  const nr = model.rewards({ mode: 'ordinary', scoreRank: normal.scoreRank, rewardBP: normal.rewardBP, eventPointBP: normal.eventPointBP, liveBoost: 10 });
  const plan = planChallengeSpending(p.challengeCosts, nr.challengePoints * 10);
  const totals = { ...plan, normalPlays: 10, liveBoost: 100, totalBadges: plan.badges + nr.badges * 10,
    totalEventPoints: plan.eventPoints + nr.eventPoints * 10, seconds: 10 * normal.duration + plan.plays * challenge.duration };
  supplement.profiles.find(x => x.rank === p.rank).mixedBudgetPlan = totals;
  lines.push(`| ${p.rank === 1 ? '0 次' : '4 次'} | ${fmt(nr.challengePoints * 10)} | ${plan.consumption.map(c => `${c.cost} × ${c.plays}`).join(' + ')} | ${plan.remainingCP} | ${fmt(totals.totalBadges)} | ${fmt(totals.seconds / 60)} |`);
}
lines.push('', '高消耗档位不提高每挑战 PT 的基础收益，但可减少演出次数。尾数用较低档位补齐；不能把未花掉的 PT 当成已到手徽章。', '', '## 具体配对', '');
for (const p of result.profiles) for (const [key, goal] of [['cpFinals', '攒挑战 PT'], ['normalFinals', '普通刷徽章'], ['challenges', '挑战刷徽章']]) {
  const r = p[key][0];
  lines.push(`### ${stage(p.rank)}：${goal}`, '', `${r.name} / ${difficulties[r.difficulty]}，加成 +${fmt(r.rewardBP / 100)}%，最低／平均参考分 ${fmt(r.minimumScore)} / ${fmt(r.expectedScore)}。第三槽为队长。`, '',
    '| 槽位 | 成员 | 留影 | 成员／留影收益加成 |', '| --- | --- | --- | --- |');
  for (const [i, s] of r.slots.entries()) lines.push(`| ${i + 1}${i === 2 ? '（队长）' : ''} | ${s.member} | ${s.support} | +${s.memberBonus}% / +${s.supportBonus}% |`);
  lines.push('');
}
lines.push('## 复现与验证', '', '```sh',
  'python3 -m tools.event_efficiency_inputs --input output/formal-inputs/jp-current-20260930-v3 --output output/verification/event-efficiency-20260930/inputs.json',
  'node tools/calculate_event_efficiency.mjs output/verification/event-efficiency-20260930/inputs.json output/verification/event-efficiency-20260930/final-results.json',
  'node tools/report_event_efficiency.mjs output/verification/event-efficiency-20260930/inputs.json output/verification/event-efficiency-20260930/final-results.json analysis/2026-09-30-event-efficiency-calculation.md',
  'node --test site/tests/event-efficiency.test.mjs site/tests/event-guide.test.mjs site/tests/event-content.test.mjs site/tests/event-card-model.test.mjs', '```', '',
  '原生证据：`output/verification/event-efficiency-20260930/native-evidence.txt`；能力倍率与取整：`output/verification/event-bonus-20260930/calculation-disassembly.txt`。参考计分身份及输入摘要保留在 JSON 中。', '');
writeFileSync(markdownPath, lines.join('\n'));
writeFileSync(resultPath.replace('.json', '-budget.json'), JSON.stringify(supplement, null, 2) + '\n');
console.log(markdownPath);
