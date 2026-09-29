// Shared across previews; cancelling a model does not invalidate a reusable runtime.
let corePromise;
export function loadLive2DCore(coreUrl) {
  if (globalThis.Live2DCubismCore) return Promise.resolve();
  corePromise ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = coreUrl;
    const fail = message => { clearTimeout(timer); script.remove(); reject(new Error(message)); };
    const timer = setTimeout(() => fail('Cubism Core timed out'), 30_000);
    script.onload = () => {
      if (!globalThis.Live2DCubismCore) { fail('Cubism Core did not initialize'); return; }
      clearTimeout(timer); resolve();
    };
    script.onerror = () => fail('Cubism Core could not load');
    document.head.append(script);
  }).catch(error => { corePromise = null; throw error; });
  return corePromise;
}
