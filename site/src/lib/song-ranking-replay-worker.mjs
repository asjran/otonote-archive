import { checkedJson } from '../runtime/content.mjs';
import { calculateSongSkillReplay } from './song-skill-replay.mjs';
import { createCalculationScheduler } from './calculation-scheduler.mjs';

self.addEventListener('message', async ({ data }) => {
  const rulesByUrl = new Map(), failures = [], yieldControl = createCalculationScheduler();
  try {
    const { candidates, skills, frameRate } = data;
    for (const [index, candidate] of candidates.entries()) {
      try {
        const source = candidate.replaySource;
        if (!source) throw new Error('缺少绑定的谱面或规则');
        const rulesKey = source.rules.url + source.rules.sha256;
        if (!rulesByUrl.has(rulesKey)) rulesByUrl.set(rulesKey, checkedJson(source.rules.url, source.rules.sha256));
        const [rules, raw] = await Promise.all([rulesByUrl.get(rulesKey), checkedJson(source.chart.url, source.chart.sha256)]);
        if (rules.sourceReleaseId !== source.releaseId || raw.sourceReleaseId && raw.sourceReleaseId !== source.releaseId
          || raw.id !== candidate.sourceId || raw.trackId !== candidate.trackId || raw.difficulty !== candidate.difficulty) throw new Error('谱面或规则版本不一致');
        await yieldControl();
        const result = calculateSongSkillReplay({ rules, chart: { ...raw, sourceReleaseId: source.releaseId },
          skills, power: candidate.power, frameRate });
        self.postMessage({ type: 'row', id: candidate.id, result });
        await yieldControl();
      } catch (error) { failures.push({ id: candidate.id, title: candidate.title, message: error.message }); }
      self.postMessage({ type: 'progress', done: index + 1, total: candidates.length, failed: failures.length });
    }
    self.postMessage({ type: 'done', failures });
  } catch (error) { self.postMessage({ type: 'error', message: error.message }); }
});
