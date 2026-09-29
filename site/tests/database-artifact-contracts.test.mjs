import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sources = Object.fromEntries(
  await Promise.all(
    ["game-database.ts", "game-modes.ts", "band-items.ts"].map(async (name) => [
      name,
      await readFile(new URL(`../src/lib/${name}`, import.meta.url), "utf8")
    ])
  )
);

test("database entry points validate generated artifacts before publishing them", () => {
  for (const [name, source] of Object.entries(sources)) {
    assert.match(
      source,
      /import \{ validateArtifact \} from "\.\/artifact-contracts";/,
      `${name} must use the shared runtime artifact validator`
    );
    assert.match(
      source,
      /schemaVersion: 1;/,
      `${name} must pin its public schema to the supported literal version`
    );
    assert.doesNotMatch(
      source,
      /\bas (?:GameDatabase|CardDetailProjections|GameModeDatabase|BandItemDatabase)\b/,
      `${name} must not publish generated data through a blind type assertion`
    );
  }
});

test("database entry points identify every generated contract in validation errors", () => {
  assert.match(sources["game-modes.ts"], /"game-modes\.json"/);
  assert.match(sources["band-items.ts"], /"band-items\.json"/);

  for (const artifactName of [
    "database-shards/summary.json",
    "database-shards/skills-index.json",
    "database-shards/items-index.json",
    "database-shards/growth-index.json",
    "database-shards/targets.json",
    "database-shards/conditions.json",
    "database-shards/skill-level-resources.json"
  ]) {
    assert.match(
      sources["game-database.ts"],
      new RegExp(`"${artifactName.replace(/[./-]/g, "\\$&")}"`)
    );
  }
});
