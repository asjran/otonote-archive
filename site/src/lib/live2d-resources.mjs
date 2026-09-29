// A bounded cache of completed, verified downloads; aborted partial files never enter it.
export function createResourceCache(limit = 64 * 1024 * 1024) {
  const entries = new Map();
  let bytes = 0;
  return {
    get(key) {
      const value = entries.get(key);
      if (value) { entries.delete(key); entries.set(key, value); }
      return value;
    },
    set(key, value) {
      if (value.size > limit) return;
      if (entries.has(key)) bytes -= entries.get(key).size;
      entries.delete(key); entries.set(key, value); bytes += value.size;
      while (bytes > limit) {
        const oldest = entries.keys().next().value;
        bytes -= entries.get(oldest).size; entries.delete(oldest);
      }
    },
    get bytes() { return bytes; }
  };
}

const cache = createResourceCache();
export const abortError = () => new DOMException('Cancelled', 'AbortError');

export async function readResource(url, { signal, onBytes = () => {}, expectedBytes,
  fetcher = fetch, timeoutMs = 30_000 } = {}) {
  const controller = new AbortController();
  let timer;
  const cancel = () => controller.abort(signal.reason ?? abortError());
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(new Error('Download timed out')), timeoutMs);
  };
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  arm();
  let reader;
  try {
    const response = await fetcher(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${new URL(url, 'http://local/').pathname}`);
    const chunks = [];
    let loaded = 0;
    if (response.body) {
      reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        controller.signal.throwIfAborted();
        arm(); loaded += value.byteLength; chunks.push(value); onBytes(loaded);
      }
    } else {
      const data = await response.arrayBuffer(); loaded = data.byteLength; chunks.push(data); onBytes(loaded);
    }
    controller.signal.throwIfAborted();
    if (expectedBytes != null && loaded !== expectedBytes) throw new Error(`Resource size mismatch: ${url}`);
    return new Blob(chunks, { type: response.headers.get('content-type') || 'application/octet-stream' });
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
}

export function validateManifest(manifest) {
  if (!Array.isArray(manifest.resources) || !manifest.resources.length || manifest.resources.length > 1000)
    throw new Error('Invalid model resource manifest');
  const names = new Set();
  for (const entry of manifest.resources) {
    if (!/^[a-zA-Z0-9_.\/-]+$/.test(entry.file) || entry.file.startsWith('/') || entry.file.split('/').includes('..') ||
        names.has(entry.file) || !Number.isSafeInteger(entry.bytes) || entry.bytes <= 0 || !/^[a-f0-9]{64}$/.test(entry.sha256))
      throw new Error('Invalid model resource entry');
    names.add(entry.file);
  }
  if (!names.has(manifest.model) || manifest.totalBytes !== manifest.resources.reduce((n, r) => n + r.bytes, 0))
    throw new Error('Invalid model resource totals');
  const bundle = manifest.jsonBundle;
  if (bundle != null && (!/^[a-zA-Z0-9_-]+\.json$/.test(bundle.file) || names.has(bundle.file) ||
      !Number.isSafeInteger(bundle.bytes) || bundle.bytes <= 0 || !/^[a-f0-9]{64}$/.test(bundle.sha256) ||
      !Array.isArray(bundle.files) || !bundle.files.length || new Set(bundle.files).size !== bundle.files.length ||
      bundle.files.some(name => typeof name !== 'string' || !name.endsWith('.json') || !names.has(name))))
    throw new Error('Invalid model JSON bundle');
  return manifest;
}

async function verifyBlob(blob, entry) {
  if (blob.size !== entry.bytes) throw new Error(`Resource size mismatch: ${entry.file}`);
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  const hex = [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
  if (hex !== entry.sha256) throw new Error(`Resource checksum mismatch: ${entry.file}`);
}

export async function loadModelResources(root, { signal, onProgress = () => {}, fetcher = fetch,
  resourceCache = cache } = {}) {
  signal?.throwIfAborted();
  onProgress({ phase: 'manifest', loaded: 0, total: null });
  const manifestBlob = await readResource(new URL('manifest.json', root).href, { signal, fetcher });
  const manifest = validateManifest(JSON.parse(await manifestBlob.text()));
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason ?? abortError());
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  const loaded = new Map(), blobs = new Map();
  let cached = 0, cursor = 0;
  const progress = () => {
    if (!controller.signal.aborted) onProgress({ phase: 'download',
      loaded: [...loaded.values()].reduce((a, b) => a + b, 0), total: manifest.totalBytes, cached });
  };
  const keyFor = entry => new URL(entry.file, root).href + '#' + entry.sha256;
  const bundled = new Set(manifest.jsonBundle?.files ?? []);
  const missingBundle = [], jobs = [];
  for (const entry of manifest.resources) {
    const blob = resourceCache.get(keyFor(entry));
    if (blob) {
      cached += blob.size; loaded.set(entry.file, blob.size); blobs.set(entry.file, blob);
    } else if (bundled.has(entry.file)) missingBundle.push(entry);
    else jobs.push(entry);
  }
  // Start large binaries/textures immediately; one small JSON request takes the remaining slot.
  jobs.sort((a, b) => b.bytes - a.bytes);
  if (missingBundle.length) jobs.push(manifest.jsonBundle);
  progress();
  const worker = async () => {
    while (cursor < jobs.length) {
      controller.signal.throwIfAborted();
      const entry = jobs[cursor++];
      const url = new URL(entry.file, root).href;
      const isBundle = entry === manifest.jsonBundle;
      const blob = await readResource(url, { signal: controller.signal, expectedBytes: entry.bytes, fetcher,
        onBytes: bytes => {
          if (isBundle) {
            for (const item of missingBundle) loaded.set(item.file, Math.floor(item.bytes * bytes / entry.bytes));
          } else loaded.set(entry.file, bytes);
          progress();
        } });
      await verifyBlob(blob, entry);
      controller.signal.throwIfAborted();
      if (isBundle) {
        const payload = JSON.parse(await blob.text());
        if (payload.schemaVersion !== 1 || !payload.files || Array.isArray(payload.files) ||
            Object.keys(payload.files).length !== bundled.size ||
            [...bundled].some(name => !Object.hasOwn(payload.files, name) || typeof payload.files[name] !== 'string'))
          throw new Error('Invalid model JSON bundle contents');
        const verified = [];
        for (const item of missingBundle) {
          controller.signal.throwIfAborted();
          const part = new Blob([payload.files[item.file]], { type: 'application/json' });
          await verifyBlob(part, item);
          verified.push([item, part]);
        }
        controller.signal.throwIfAborted();
        for (const [item, part] of verified) {
          resourceCache.set(keyFor(item), part); blobs.set(item.file, part);
          loaded.set(item.file, part.size);
        }
      } else {
        resourceCache.set(keyFor(entry), blob); blobs.set(entry.file, blob);
      }
      progress();
    }
  };
  try {
    const workers = Array.from({ length: Math.min(4, jobs.length) }, () => worker().catch(error => {
      controller.abort(error); throw error;
    }));
    const results = await Promise.allSettled(workers);
    if (controller.signal.aborted) throw controller.signal.reason;
    const failed = results.find(x => x.status === 'rejected');
    if (failed) throw failed.reason;
    return { manifest, blobs };
  } finally { signal?.removeEventListener('abort', cancel); }
}
