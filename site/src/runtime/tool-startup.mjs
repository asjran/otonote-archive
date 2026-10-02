/** Prepare controls automatically; expensive actions still belong to their own buttons. */
export async function prepareTool({document, readJson, importModule, locale, onReady, onError = console.error}) {
  const region = document.querySelector('[data-tool-pending]');
  if (!region) return;
  const status = document.querySelector('[data-tool-status]');
  const gate = document.querySelector('[data-tool-gate]');
  const en = locale === 'en';
  try {
    const payloads = await Promise.all([...region.querySelectorAll('script[data-deferred-json]')].map(async node => ({
      node, value: await readJson(node.dataset.deferredJson, node.dataset.sha256)
    })));
    for (const {node, value} of payloads) node.textContent = JSON.stringify(value);
    // These modules are preloaded together by the HTML. Evaluate in order, only
    // after all JSON is present, so custom elements never see partial inputs.
    for (const script of document.querySelectorAll('script[data-deferred-module]')) {
      await importModule(script.dataset.deferredModule);
    }
    region.inert = false;
    region.removeAttribute('aria-busy');
    region.removeAttribute('data-tool-pending');
    gate?.remove();
    onReady();
  } catch (error) {
    onError(error);
    status.textContent = en ? 'Could not prepare this tool. Reload to try again.' : '工具准备失败，请重新加载后重试。';
    gate?.querySelector('[data-loading-interlude]')?.setAttribute('data-failed', '');
    const retry = document.querySelector('[data-tool-retry]');
    if (retry) retry.hidden = false;
    // Keep controls inert: ESM may already have partially initialized them.
    // A normal document reload gives retries a clean module/custom-element state.
  }
}
