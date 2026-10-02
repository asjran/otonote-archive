import {checkedJson, pageContext, validatePointer} from './content.mjs';

/** Old and new interaction bundles share this document state. Fetch lazily. */
export function pinSnapshot(pointer) {
  validatePointer(pointer);
  const context = pageContext();
  const root = pointer.manifest.slice(0, -'manifest.json'.length);
  let promise;
  const load = () => promise ??= checkedJson(pointer.manifest, pointer.sha256).then(manifest => {
    const region = manifest.region ?? (manifest.contentReleaseId?.startsWith('global-') ? 'global' : null);
    if (manifest.schemaVersion !== 1 || manifest.root !== root || region !== context.region || !manifest.locales?.[context.locale]) {
      throw new Error('网站与内容版本不兼容');
    }
    return manifest;
  });
  const key = Symbol.for('ournotes.content.snapshot.v1');
  if (globalThis[key]) throw new Error('Content snapshot already initialized');
  globalThis[key] = {documents:new Map(), pointers:pointer.libraryPointers ?? {}, promise:{then:(resolve, reject) => load().then(resolve, reject)}};
  globalThis[Symbol.for('ournotes.content-root.v1')] = root;
  return root;
}
