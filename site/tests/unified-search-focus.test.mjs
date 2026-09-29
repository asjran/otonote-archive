import assert from "node:assert/strict";
import test, { after } from "node:test";

// Minimal browser boundaries for exercising focus during a delayed index request.
const originals = new Map(["HTMLElement", "HTMLDialogElement", "customElements"].map(
  name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]
));
class Element {}
class Dialog extends Element {
  open = false;
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const registry = new Map();
globalThis.HTMLElement = Element;
globalThis.HTMLDialogElement = Dialog;
globalThis.customElements = {
  get: name => registry.get(name),
  define: (name, constructor) => registry.set(name, constructor)
};
await import("../src/lib/unified-search-client.mjs");
after(() => {
  for (const [name, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  }
});

function delayedSearch() {
  const Search = registry.get("global-search");
  const search = new Search();
  let focus = "trigger";
  let renders = 0;
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  search.dialog = new Dialog();
  search.input = { focus() { focus = "input"; } };
  search.openButton = { focus() { focus = "trigger"; } };
  search.load = () => pending;
  search.render = () => { renders++; };
  return { search, resolve, focus: () => focus, renders: () => renders, moveFocus: () => { focus = "type-filter"; } };
}

test("search focuses immediately; closing before loading finishes keeps focus on the trigger", async () => {
  const state = delayedSearch();
  const opening = state.search.open();
  assert.equal(state.focus(), "input");
  state.search.close();
  state.resolve();
  await opening;
  assert.equal(state.search.dialog.open, false);
  assert.equal(state.focus(), "trigger");
  assert.equal(state.renders(), 0);
});

test("loaded results do not steal focus from a search type control", async () => {
  const state = delayedSearch();
  const opening = state.search.open();
  state.moveFocus();
  state.resolve();
  await opening;
  assert.equal(state.search.dialog.open, true);
  assert.equal(state.focus(), "type-filter");
  assert.equal(state.renders(), 1);
});

test('failed index requests can be retried and successful requests are cached', async t => {
  const Search = registry.get('global-search');
  const search = new Search();
  search.dataset = { indexUrl: '/search-index.json', releaseId: 'r1' };
  search.render = () => {};
  let requests = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    requests++;
    if (requests === 1) throw new Error('offline');
    return { ok: true, json: async () => ({ schemaVersion: 1, sourceReleaseId: 'r1', entries: [
      { id: 'story-1', title: 'A', type: 'story', href: '/stories/episodes/story-1/' },
      { id: 'bad-1', title: 'B', type: 'music', href: '//external.example/' },
      { id: 'bad-2', title: 'C', type: 'music', href: 'javascript:alert(1)' }
    ] }) };
  });
  await search.load();
  assert.equal(search.failed, true);
  assert.equal(search.loaded, false);
  assert.equal(search.loading, null);
  await Promise.all([search.load(), search.load()]);
  assert.equal(requests, 2);
  assert.equal(search.failed, false);
  assert.equal(search.loaded, true);
  assert.deepEqual(search.entries.map(entry => entry.id), ['story-1']);
  await search.load();
  assert.equal(requests, 2);
});

test('IME confirmation cannot open a result', () => {
  const Search = registry.get('global-search');
  const search = new Search();
  search.results = { querySelectorAll() { throw new Error('IME must not navigate'); } };
  search.navigateResults({ key: 'Enter', isComposing: true });
  search.navigateResults({ key: 'Enter', keyCode: 229 });
  search.composing = true;
  search.navigateResults({ key: 'Enter' });
});
