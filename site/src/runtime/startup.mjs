import {artifact, pageContext, snapshot} from './content.mjs';
import {loadPageInputs, loadStylesheet} from './page-readiness.mjs';
import {routeParams} from './routes.mjs';

const startupKey = Symbol.for('ournotes.page-startup.v1');

/** Shell and boot share one task, including the original rejection on failure. */
export function startPageInputs(manifest, root, {importPage = url => import(url), document = globalThis.document} = {}) {
  const previous = globalThis[startupKey];
  if (previous) return previous;
  const context = pageContext();
  globalThis.__OURNOTES_BASE__ = context.base;
  globalThis[Symbol.for('ournotes.code-root.v1')] = root;
  const task = loadPageInputs(async () => {
    const content = await snapshot();
    // These existing files are shared by the layout on every page. Start all
    // three before template evaluation can serialize their top-level awaits.
    await Promise.all(['catalog', 'release-index', 'media-index'].map(name => artifact(`projection/${name}.json`)));
    return content;
  }, async () => {
    if (manifest?.schemaVersion !== 1 || manifest.contentSchemaVersion !== 1) throw new Error('网站与内容版本不兼容');
    const app = {...manifest, root};
    const path = context.route.replace(/^\/|\/$/g, '');
    let selected, params;
    for (const route of app.routes) {
      const match = routeParams(route.pattern, path);
      if (match) { selected = route; params = match; break; }
    }
    if (!selected) throw new Error('页面不存在 / Page not found');
    const [page, stylesheet] = await Promise.all([
      importPage(new URL(selected.module, root).href),
      selected.css ? loadStylesheet(new URL(selected.css, root).href, document) : null
    ]);
    return {app, page, params, stylesheet};
  });
  globalThis[startupKey] = task;
  // The inline starter runs before boot can attach its error UI. Mark the
  // rejection handled without converting the shared task into a success.
  task.catch(() => {});
  return task;
}
