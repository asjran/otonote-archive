#!/usr/bin/env node
/** Render one actual compiled route in a fresh process; record its checked data requests. */
import {readFile, writeFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {startPageInputs} from '../site/src/runtime/startup.mjs';

const [codeArg, storeArg, route = 'cards/members', locale = 'zh-CN', reportPath, htmlPath] = process.argv.slice(2);
const code = resolve(codeArg), store = resolve(storeArg);
globalThis.location = new URL(`https://preview.invalid/global/${locale}/${route}/`);
const requests = [], inFlight = new Set();
let maxParallel = 0;
globalThis.fetch = async input => {
  const url = new URL(input, location);
  if (url.origin !== location.origin || !url.pathname.startsWith('/content/')) throw Error('Unexpected request: ' + url);
  const file = resolve(store, url.pathname.slice('/content/'.length));
  if (!file.startsWith(store + '/')) throw Error('Unsafe fixture path');
  const record = {url:url.pathname, start:performance.now()};
  requests.push(record); inFlight.add(record); maxParallel = Math.max(maxParallel, inFlight.size);
  try {
    const bytes = await readFile(file);
    // Model an in-flight response so serial awaits cannot look parallel just
    // because a local fixture is read very quickly.
    await new Promise(resolve => setTimeout(resolve, 15));
    record.bytes = bytes.byteLength;
    return new Response(bytes);
  } catch (error) { if (error.code === 'ENOENT') return new Response('', {status:404}); throw error; }
  finally {record.end = performance.now(); inFlight.delete(record);}
};
const app = JSON.parse(await readFile(join(code, 'compiled/manifest.json'), 'utf8'));
const codeRoot = pathToFileURL(join(code, 'compiled') + '/').href;
const fakeDocument = {createElement:() => ({remove(){}}), head:{append:link => queueMicrotask(() => link.onload())}};
const {content, route:{page, params}} = await startPageInputs(app, codeRoot, {document:fakeDocument});
const shell = await readFile(join(code, 'index.html'), 'utf8');
const boot = shell.match(/src="\/app\/releases\/[a-f0-9]+\/([^"]+)"/)[1];
const {renderToString, renderContext} = await import(new URL(boot, codeRoot));
let props = {};
if (page.getStaticPaths) props = (await page.getStaticPaths({})).find(item => Object.entries(params).every(([key, value]) => String(item.params?.[key]) === value))?.props ?? {};
const html = await renderToString(renderContext(location, params, {...app, root:codeRoot}), page.default, props, {}, true);
if (typeof html !== 'string' || !html.includes('<main')) throw Error('Route did not render');
if (htmlPath) await writeFile(htmlPath, html.replaceAll(codeRoot, 'https://code.invalid/'));
const dataRequests = requests.filter(item => !item.url.endsWith('/manifest.json') && !item.url.endsWith('/current.json'));
const unexpected = ['items.json', 'growth.json', 'skill-level-resources.json', route === 'cards/members' ? 'support-cards.json' : 'member-cards.json'];
const issues = [];
if (/^cards\/(members|supports)$/.test(route)) {
  if (dataRequests.some(item => unexpected.some(name => item.url.endsWith('/' + name)))) issues.push('Card list loads unrelated database collections');
  if (dataRequests.length !== 5) issues.push(`Expected 5 page data files, got ${dataRequests.length}`);
  if (maxParallel < 5) issues.push(`Expected 5 overlapping data reads, got ${maxParallel}`);
}
if (new Set(requests.map(item => item.url)).size !== requests.length) issues.push('Duplicate content request');
const report = {route, locale, snapshot:content.root, maxParallel, dataFiles:dataRequests.length, decodedBytes:requests.reduce((sum, item) => sum + (item.bytes ?? 0), 0), requests, issues};
if (reportPath) await writeFile(reportPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify({route, locale, maxParallel, dataFiles:report.dataFiles, decodedBytes:report.decodedBytes, issues}));
if (issues.length) process.exitCode = 1;
