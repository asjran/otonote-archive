import { loadLive2DCore } from './live2d-core.mjs';
import { loadModelResources, abortError } from './live2d-resources.mjs';

// Start all downloads at the click boundary, before waiting for any one of them.
export async function loadLive2DPreview(root, coreUrl, { signal, onProgress,
  loadResources = loadModelResources, loadCore = loadLive2DCore,
  loadPlayer = () => import('./live2d-player.mjs') } = {}) {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason ?? abortError());
  signal?.addEventListener('abort', cancel, { once: true });
  let rejectAbort;
  const aborted = new Promise((_, reject) => { rejectAbort = () => reject(controller.signal.reason); });
  controller.signal.addEventListener('abort', rejectAbort, { once: true });
  try {
    const player = Promise.all([
      Promise.resolve().then(() => loadCore(coreUrl)),
      Promise.resolve().then(() => loadPlayer()),
    ]).then(async ([, module]) => {
      await module.prepareLive2DPlayer(coreUrl);
      return module;
    });
    const ready = Promise.all([
      Promise.resolve().then(() => loadResources(root, { signal: controller.signal, onProgress })), player,
    ]);
    const [resources, module] = await Promise.race([ready, aborted]);
    controller.signal.throwIfAborted();
    return { resources, createLive2DPlayer: module.createLive2DPlayer };
  } catch (error) {
    controller.abort(error);
    throw error;
  } finally {
    signal?.removeEventListener('abort', cancel);
    controller.signal.removeEventListener('abort', rejectAbort);
  }
}
