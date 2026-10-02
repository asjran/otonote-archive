import { createPerformanceTemplate, validatePerformance } from './scoring-rules/formal-performance-replay.mjs';
import { getRuntimeUiLabels } from './runtime-ui-labels.ts';

const MAX_BYTES = 8 * 1024 * 1024;

export function parsePerformanceInput(text, rules, chart, labels = getRuntimeUiLabels('zh-CN').scoringResearch.performance) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).length > MAX_BYTES) throw new Error(labels.tooLarge);
  let value;
  try { value = JSON.parse(text); } catch { throw new Error(labels.invalidJson); }
  validatePerformance(rules, chart, value);
  return value;
}

/** Keep the editable text separate from the last applied input. Changing songs
 * clears both, so a previous chart can never silently supply its judgements. */
export function setupPerformanceInput(root, { getChart, rules, recalculate, labels = getRuntimeUiLabels('zh-CN').scoringResearch.performance }) {
  const find = name => root.querySelector(`[data-performance-${name}]`);
  let applied = null, chartId = null, fileRequest = 0;
  const status = message => { find('status').textContent = message; };
  const apply = () => {
    applied = null;
    find('mode').value = 'explicit';
    try {
      applied = parsePerformanceInput(find('json').value, rules, getChart(), labels);
      status(labels.applied.replace('{count}',String(applied.judgements.length)).replace('{order}',applied.skillOrder.map(n=>n+1).join(' → ')));
    } catch (error) { status(error.message); }
    recalculate();
  };
  find('apply').addEventListener('click', apply);
  find('reset').addEventListener('click', () => {
    applied = null; fileRequest++;
    find('mode').value = 'ap'; find('json').value = ''; find('file').value = '';
    status(labels.reset); recalculate();
  });
  find('mode').addEventListener('change', recalculate);
  find('file').addEventListener('change', async () => {
    const file = find('file').files?.[0]; if (!file) return;
    const request = ++fileRequest;
    try {
      if (file.size > MAX_BYTES) throw new Error(labels.tooLarge);
      const text = await file.text(); if (request !== fileRequest) return;
      find('json').value = text; apply();
    } catch (error) {
      if(request === fileRequest){applied=null;find('mode').value='explicit';status(error.message);recalculate();}
    }
  });
  find('template').addEventListener('click', () => {
    try {
      const chart = getChart();
      if (!chart?.notes?.length) throw new Error(labels.chooseChart);
      const template = createPerformanceTemplate(rules, chart);
      const text = JSON.stringify(template, null, 2);
      find('json').value = text;
      const url = URL.createObjectURL(new Blob([text], {type:'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `${chart.id}-performance.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      status(labels.templateReady);
    } catch (error) { status(error.message); }
  });
  return {
    get value() {
      if (find('mode').value !== 'explicit') return null;
      if (!applied) throw new Error(labels.notApplied);
      return applied;
    },
    sync(chart) {
      if (chartId !== chart?.id) {
        fileRequest++; applied = null; find('mode').value = 'ap'; find('json').value = ''; find('file').value = '';
        status(labels.chartBound); chartId = chart?.id;
      }
      find('template').disabled = !chart?.notes?.length;
    },
    destroy() { fileRequest++; }
  };
}
