import { songSkillProfileKey } from './song-skill-profile.mjs';
import { withSongSkillReplay } from './song-ranking-replay-result.mjs';

/** Keeps the expensive candidate comparison cancellable and scoped. A replay
 * board contains completed candidates only; no mixed-precision global rank. */
export function setupSongRankingReplay(root, change) {
  const q = name => root.querySelector(`[data-replay-${name}]`);
  const say = (zh, en) => document.documentElement.lang.startsWith('en') ? en : zh;
  let key = '', context, worker = null, done = 0, total = 0, failures = [], message = '';
  const results = new Map();
  function stop() { worker?.terminate(); worker = null; }
  function renderStatus() {
    q('cancel').hidden = !worker;
    q('run').disabled = !!worker || !context?.valid || !context.rows.some(row => row.replaySource);
    q('panel').setAttribute('aria-busy', String(!!worker));
    q('status').textContent = worker ? say(`逐谱精算 ${done} / ${total} 张谱面${failures.length ? `，${failures.length} 张失败` : ''}…`, `Replaying ${done} / ${total} charts${failures.length ? `, ${failures.length} failed` : ''}…`)
      : message || (results.size ? say(`已完成 ${results.size} 张谱面。当前名次只比较这些已算谱面；调整技能或帧率后需重新计算。`, `${results.size} charts complete. Ranks compare completed charts only; run again after changing skills or frame rate.`)
        : say('选好歌曲与技能后，可计算当前排序前 25 张或全部匹配谱面；计算期间可以停止。', 'Choose songs and skills, then replay the first 25 charts in the current order or all matching charts. You can stop at any time.'));
    const errors = q('errors'); errors.replaceChildren(); errors.hidden = !failures.length;
    if (failures.length) {
      const summary = document.createElement('summary'); summary.textContent = say(`${failures.length} 张谱面未完成，可重试`, `${failures.length} charts incomplete; try again`); errors.append(summary);
      const list = document.createElement('ul');
      for (const failure of failures) { const item = document.createElement('li'); item.textContent = `${failure.title}：${failure.message}`; list.append(item); }
      errors.append(list);
    }
  }
  const run = () => {
    if (worker || !context.valid) return;
    const scoped = q('scope').value === 'all' ? context.rows : context.rows.slice(0, 25);
    const candidates = scoped.filter(row => row.replaySource).map(row => ({ id: row.id, sourceId: row.sourceId,
      title: `${row.title} ${row.difficulty.toUpperCase()}`, trackId: row.trackId.replace(/^(global|jp)--/, ''),
      difficulty: row.difficulty, power: row.benchmark.power, replaySource: row.replaySource }));
    if (!candidates.length) { message = say('当前筛选缺少完整谱面与计分规则，暂不能逐谱精算。', 'The current selection has no complete chart and scoring data for replay.'); renderStatus(); return; }
    done = 0; total = candidates.length; failures = []; message = '';
    const omitted = scoped.length - candidates.length;
    try {
      worker = new Worker(new URL('./song-ranking-replay-worker.mjs', import.meta.url), { type: 'module' });
      const active = worker;
      q('method').value = 'replay';
      worker.addEventListener('message', ({ data }) => {
        if (worker !== active) return;
        if (data.type === 'row') { results.set(data.id, data.result); return; }
        if (data.type === 'progress') { done = data.done; renderStatus(); change(); return; }
        stop();
        if (data.type === 'done') {
          failures = data.failures;
          message = say(`本次完成 ${total - failures.length} / ${total} 张谱面${omitted ? `，另有 ${omitted} 张缺少绑定数据` : ''}。只比较已完成的谱面；可切回“全部筛选结果”与原列表核对。`, `Completed ${total - failures.length} / ${total} charts${omitted ? `; ${omitted} lack linked data` : ''}. Only completed charts are ranked. Switch to all filtered results to compare with the original list.`);
        } else message = say(`逐谱精算失败：${data.message}`, `Chart replay failed: ${data.message}`);
        change();
      });
      worker.addEventListener('error', () => {
        if (worker !== active) return;
        stop(); message = say('计算服务加载失败；已完成结果保留，可重试。', 'The calculation service could not load. Completed results are kept; try again.'); change();
      });
      worker.postMessage({ candidates, skills: context.skills, frameRate: context.frameRate });
    } catch (error) { stop(); message = say(`无法开始逐谱精算：${error.message}`, `Could not start chart replay: ${error.message}`); }
    change();
  };
  const listeners = new AbortController();
  q('run').addEventListener('click', run, { signal: listeners.signal });
  q('cancel').addEventListener('click', () => {
    stop(); message = say(`已停止计算，保留 ${results.size} 张已完成结果。`, `Stopped. ${results.size} completed chart results are kept.`); change();
  }, { signal: listeners.signal });
  for (const name of ['method', 'fps']) q(name).addEventListener('change', change, { signal: listeners.signal });
  return {
    sync({ skills, rows, mode, profile = 'benchmark' }) {
      const frameRate = Number(q('fps').value);
      let next; try { next = songSkillProfileKey(skills, frameRate); } catch { next = 'invalid'; }
      if (next !== key) { stop(); key = next; results.clear(); failures = []; message = ''; q('method').value = 'linear'; }
      if (mode !== 'ordinary') stop();
      context = { skills, rows, frameRate, valid: mode === 'ordinary' && next !== 'invalid' };
      q('panel').hidden = mode !== 'ordinary';
      q('description').textContent = profile === 'custom'
        ? say('快速估算已可用于选曲。想比较接近的结果时，可逐个音符重新计算技能覆盖与取整，遍历全部 120 种发动顺序。', 'Quick estimates are ready for song selection. For close results, replay every note with skill coverage and rounding across all 120 skill orders.')
        : profile === 'none' ? say('无技能基础分已逐音符计算，可直接比较；也可按所选帧率回放当前筛出的谱面。', 'No-skill scores were already calculated note by note. You can also replay the filtered charts at the selected frame rate.')
        : say('基准榜已按 60 FPS 预先逐音符计算，可直接使用。需要比较另一帧率时，再运行逐谱精算。', 'The benchmark was already calculated note by note at 60 FPS. Replay charts when you want to compare another frame rate.');
      renderStatus();
      return mode === 'ordinary' && q('method').value === 'replay';
    },
    rows(source) {
      return source.filter(row => results.has(row.id)).flatMap(row => {
        try {
          const result = results.get(row.id);
          return result.profileKey === key ? [{ ...withSongSkillReplay(row, result), linearScore: row.expectedScore, comparisonLabel: row.calculation === 'linear'
              ? row.skillProfile?.every(skill => !skill.percent || !skill.seconds) ? say('无技能基础分', 'No-skill baseline') : say('快速估算', 'Quick estimate') : say('基准预计算', 'Precomputed benchmark') }] : [];
        } catch { return []; }
      });
    },
    destroy() { stop(); listeners.abort(); }
  };
}
