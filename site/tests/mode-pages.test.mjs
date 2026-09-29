import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readSource = (path) =>
  readFile(new URL(path, import.meta.url), "utf8");

test("retains shared game mode source data for the event archive", async () => {
  const gameModes = JSON.parse(
    await readSource("../src/data/generated/game-modes.json")
  );
  assert.deepEqual(
    gameModes.modes.map((mode) => mode.id),
    ["battle-live", "gekisou"]
  );
  assert.equal(gameModes.modes.some((mode) => mode.id === "solo-live"), false);
});

test("Arena stays empty when no complete server season is available", async () => {
  const arena = JSON.parse(
    await readSource("../src/data/generated/arena-rank.json")
  );
  assert.equal(arena.currentSeason, null);
  assert.deepEqual(arena.pastSeasons, []);
  assert.equal(arena.status, "server_unavailable");
});
