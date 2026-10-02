import {renderToString, renderContext} from './astro.mjs';
import {localizeHtmlWithStats} from '../lib/html-localizer.ts';
import {routeParams} from './routes.mjs';

export async function renderPageResource(input, app, context, options = {}) {
  options.signal?.throwIfAborted();
  const url = new URL(input, location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith(context.base)) throw new Error('Unsupported page resource');
  const logical = url.pathname.slice(context.base.length).replace(/\/$/, '');
  const endpoint = app.endpoints[logical];
  if (endpoint) return (await import(new URL(endpoint.module, app.root).href)).GET();
  const route = app.routes.find(r => r.pattern === 'database/details/[...record]');
  const params = route && routeParams(route.pattern, logical);
  if (!params) throw new Error('Unknown page resource');
  const page = await import(new URL(route.module, app.root).href);
  const entry = (await page.getStaticPaths({})).find(p => p.params.record === params.record);
  if (!entry) return new Response('', {status:404});
  let html = await renderToString(renderContext(url, params, app), page.default, entry.props, {}, false);
  if (context.locale === 'en') html = localizeHtmlWithStats(html, 'en').html;
  options.signal?.throwIfAborted();
  return new Response(html, {headers:{'Content-Type':'text/html; charset=utf-8'}});
}
