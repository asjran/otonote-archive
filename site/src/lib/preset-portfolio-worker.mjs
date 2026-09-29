import { evaluatePresetPool } from './preset-portfolio.mjs';
import { generatePresetCandidates } from './preset-candidates.mjs';
self.onmessage = async ({ data }) => {
  const { requestId, type, payload } = data;
  try {
    const options = { onProgress: progress => self.postMessage({ type: 'progress', requestId, progress }),
      yieldControl: () => new Promise(resolve => setTimeout(resolve, 0)) };
    if (!['generate', 'evaluate'].includes(type)) throw new Error('未知预设任务');
    const result = await (type === 'generate' ? generatePresetCandidates(payload, options) : evaluatePresetPool(payload, options));
    self.postMessage({ type: 'result', requestId, result });
  } catch (error) { self.postMessage({ type: 'error', requestId, error: error.message }); }
};
