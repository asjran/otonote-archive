// The existing templates use only Astro's pure HTML rendering runtime.
export * from 'astro/runtime/server/index.js';
export function createMetadata() { return {}; }
export function renderContext(url, params, app) {
  return {
    styles: new Set(), scripts: new Set(), links: new Set(),
    clientDirectives: new Map(), componentMetadata: new Map(), inlinedScripts: new Map(), renderers: [],
    base: '/', partial: false, compressHTML: false,
    _metadata: { hasRenderedHead: false, headInTree: true, extraHead: [], propagators: new Set(),
      pendingSlotEvaluations: [], renderedScripts: new Set(), rendererSpecificHydrationScripts: new Set() },
    resolve: async id => {
      if (!app.scripts[id]) throw new Error('Missing compiled interaction: ' + id);
      return new URL(app.scripts[id], app.root).href;
    },
    createAstro(...args) {
      const [props, slots] = args.length === 3 ? args.slice(1) : args;
      return { props, params, url, generator: 'OtoNote',
        slots: { has: name => !!slots[name] },
        redirect: location => Response.redirect(new URL(location, url), 302) };
    }
  };
}
