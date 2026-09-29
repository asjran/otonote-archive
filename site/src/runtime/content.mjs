/** One immutable content snapshot per document, shared by independently loaded modules. */
const stateKey = Symbol.for('ournotes.content.snapshot.v1');
function state() {
  return globalThis[stateKey] ??= { documents: new Map() };
}
export function pageContext(pathname = globalThis.location?.pathname ?? '/global/zh-CN/') {
  const match = pathname.match(/^\/global\/(zh-CN|en)(\/.*)?$/);
  return { locale: match?.[1] ?? 'zh-CN', base: `/global/${match?.[1] ?? 'zh-CN'}/`, route: match?.[2] ?? '/' };
}
export async function checkedJson(url, expected, fetcher = fetch) {
  const response = await fetcher(url, { cache: expected ? 'force-cache' : 'no-store', credentials: 'same-origin', signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error(`内容读取失败 (${response.status})`);
  const bytes = await response.arrayBuffer();
  if (expected) {
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
    if (hash !== expected) throw new Error('内容校验失败，请稍后重试');
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
export function validatePointer(value) {
  if (value?.schemaVersion !== 1 || !/^\/content\/releases\/[a-f0-9]{24}\/manifest\.json$/.test(value.manifest)
      || !/^[a-f0-9]{64}$/.test(value.sha256)) throw new Error('网站与内容版本不兼容');
  return value;
}
export async function snapshot() {
  const shared = state();
  shared.promise ??= (async () => {
    const pointer = validatePointer(await checkedJson('/content/current.json'));
    const manifest = await checkedJson(pointer.manifest, pointer.sha256);
    const root = pointer.manifest.slice(0, -'manifest.json'.length);
    if (manifest.schemaVersion !== 1 || manifest.root !== root || !manifest.locales?.[pageContext().locale]) {
      throw new Error('网站与内容版本不兼容');
    }
    // Publish the validated root before any parallel template import can derive
    // media URLs from its data. Import completion must not control this timing.
    globalThis[Symbol.for('ournotes.content-root.v1')] = root;
    return manifest;
  })();
  return shared.promise;
}
async function readRecord(record) {
  const manifest = await snapshot();
  if (!record || typeof record.path !== 'string' || record.path.startsWith('/') || record.path.split('/').some(p => !p || p === '..')
      || /[%?#\\]/.test(record.path) || !/^[a-f0-9]{64}$/.test(record.sha256)) throw new Error('内容文件清单不完整');
  const url = manifest.root + record.path;
  const shared = state();
  if (!shared.documents.has(url)) shared.documents.set(url, checkedJson(url, record.sha256));
  return shared.documents.get(url);
}
export async function artifact(name, {optional = false} = {}) {
  const manifest = await snapshot();
  const record = manifest.locales[pageContext().locale].files[name];
  if (optional && !record) return null;
  return readRecord(record);
}
export async function artifactGlob(pattern, options = {}) {
  const manifest = await snapshot();
  const records = manifest.locales[pageContext().locale];
  const prefix = '@projection-data/';
  if (!pattern.startsWith(prefix)) throw new Error('不支持的内容分组');
  if (!pattern.includes('*')) {
    const value = await artifact('projection/' + pattern.slice(prefix.length));
    return { [pattern]: options.import === 'default' ? value : { default: value } };
  }
  let values;
  if (pattern === '@projection-data/story-text/*.json') {
    const id = pageContext().route.match(/^\/stories\/episodes\/([^/]+)\/?$/)?.[1];
    if (!id) return {};
    const name = 'projection/story-text/' + id + '.json';
    if (!records.files[name]) return {};
    values = { [pattern.replace('*', id)]: await artifact(name) };
  } else {
    values = await readRecord(records.groups[pattern]);
  }
  return Object.fromEntries(Object.entries(values).map(([name, value]) => [name, options.import === 'default' ? value : { default: value }]));
}
