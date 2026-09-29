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
