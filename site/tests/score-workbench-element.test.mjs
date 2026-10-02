import assert from "node:assert/strict";
import test from "node:test";

import * as scoreWorkbenchElement from "../src/lib/score-workbench-element.ts";

const { createLatestChartLoader } = scoreWorkbenchElement;

test("a late difficulty response cannot replace the latest selection", async () => {
  const pending = new Map();
  const loadLatest = createLatestChartLoader(
    (url) =>
      new Promise((resolve) => {
        pending.set(url, resolve);
      }),
    new Map()
  );

  const slow = loadLatest("chart-hard", "/hard.json");
  const fast = loadLatest("chart-expert", "/expert.json");

  pending.get("/expert.json")({ id: "chart-expert" });
  assert.deepEqual(await fast, {
    status: "current",
    chart: { id: "chart-expert" }
  });

  pending.get("/hard.json")({ id: "chart-hard" });
  assert.deepEqual(await slow, { status: "stale" });
});

test("page summary difficulty stays synced with URL and browser history", () => {
  const selected = [];
  const location = { search: "?difficulty=hard" };
  const coordinator = scoreWorkbenchElement.createScoreDifficultyCoordinator({
    difficulties: ["easy", "normal", "hard", "expert"],
    readSearch: () => location.search,
    replaceDifficulty: (difficulty) => {
      location.search = `?difficulty=${difficulty}`;
    },
    onSelect: (difficulty) => selected.push(difficulty)
  });

  coordinator.syncFromLocation();
  coordinator.selectFromSummary("easy");
  location.search = "?difficulty=normal";
  coordinator.syncFromLocation();

  assert.deepEqual(
    { selected, search: location.search },
    { selected: ["hard", "easy", "normal"], search: "?difficulty=normal" }
  );
});

test('hidden or closed analysis never overwrites the chart playback position', () => {
  const names = ['HTMLElement', 'customElements', 'location', 'history'];
  const descriptors = new Map(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  let elementType, written = [];
  try {
    globalThis.HTMLElement = class {};
    globalThis.customElements = { get: () => undefined, define: (_name, type) => { elementType = type; } };
    globalThis.location = { pathname: '/global/zh-CN/music/music-1/', search: '?view=playback&t=10.71&loopStart=10&loopEnd=11', hash: '' };
    globalThis.history = { replaceState: (_state, _title, url) => written.push(url) };
    scoreWorkbenchElement.registerScoreWorkbenchElement();
    let hidden = true, open = true;
    const view = {
      start: 0,
      closest: selector => selector === 'dialog' ? { open } : { hidden },
      querySelector: () => ({ dataset: { difficulty: 'hard' } }),
    };
    elementType.prototype.updateUrl.call(view);
    hidden = false; open = false;
    elementType.prototype.updateUrl.call(view);
    assert.deepEqual(written, []);
    open = true;
    globalThis.location.search = '?view=analysis&t=10.71';
    elementType.prototype.updateUrl.call(view);
    assert.equal(written.length, 1);
    assert.equal(new URL(written[0], 'https://test.invalid').searchParams.get('t'), '0.0');
  } finally {
    for (const name of names) {
      const descriptor = descriptors.get(name);
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});
