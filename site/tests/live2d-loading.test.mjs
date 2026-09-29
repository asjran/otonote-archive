import test from 'node:test';
import assert from 'node:assert/strict';
import { loadLive2DPreview } from '../src/lib/live2d-loading.mjs';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise(resolve => setImmediate(resolve));

test('player and core download while model is blocked; module evaluation waits for Core', async () => {
  const model = deferred(), core = deferred(), calls = [];
  const createLive2DPlayer = () => {};
  const pending = loadLive2DPreview('root', 'core', {
    loadResources: () => { calls.push('model'); return model.promise; },
    loadCore: () => { calls.push('core'); return core.promise; },
    loadPlayer: async () => { calls.push('player'); return {
      prepareLive2DPlayer: async () => calls.push('evaluate'), createLive2DPlayer,
    }; },
  });
  await tick();
  assert.deepEqual(new Set(calls), new Set(['core', 'player', 'model']));
  core.resolve(); await tick(); assert.ok(calls.includes('evaluate'));
  model.resolve({ model: true });
  assert.deepEqual(await pending, { resources: { model: true }, createLive2DPlayer });
});

test('cancel exits even after model finishes while shared runtime is still pending', async () => {
  const controller = new AbortController(), core = deferred();
  let resourceSignal;
  const pending = loadLive2DPreview('root', 'core', { signal: controller.signal,
    loadResources: async (_root, { signal }) => { resourceSignal = signal; return {}; },
    loadCore: () => core.promise,
    loadPlayer: async () => ({ prepareLive2DPlayer: async () => {}, createLive2DPlayer() {} }),
  });
  await tick(); controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.ok(resourceSignal.aborted);
  // Late failure is handled and cannot resume the cancelled preview.
  core.reject(new Error('late failure')); await tick();
});

test('runtime failure aborts outstanding model work and a retry succeeds', async () => {
  let aborted = false;
  await assert.rejects(loadLive2DPreview('root', 'core', {
    loadCore: async () => { throw Error('Core unavailable'); },
    loadPlayer: async () => ({}),
    loadResources: (_, { signal }) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => { aborted = true; reject(signal.reason); });
    }),
  }), /Core unavailable/);
  assert.ok(aborted);
  const result = await loadLive2DPreview('root', 'core', {
    loadCore: async () => {}, loadResources: async () => 'ready',
    loadPlayer: async () => ({ prepareLive2DPlayer: async () => {}, createLive2DPlayer() {} }),
  });
  assert.equal(result.resources, 'ready');
});

test('already-cancelled previews start no downloads', async () => {
  const controller = new AbortController(); controller.abort();
  const unexpected = () => { throw Error('download started'); };
  await assert.rejects(loadLive2DPreview('root', 'core', { signal: controller.signal,
    loadCore: unexpected, loadPlayer: unexpected, loadResources: unexpected }), { name: 'AbortError' });
});
