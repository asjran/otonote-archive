import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const readSource = (path) =>
  readFile(new URL(path, import.meta.url), "utf8");

test("card archive entrances keep visitors inside the active projection", async () => {
  const [entry, memberTile, supportTile] = await Promise.all([
    readSource("../src/pages/cards/index.astro"),
    readSource("../src/components/MemberCardTile.astro"),
    readSource("../src/components/SupportCardTile.astro")
  ]);

  assert.doesNotMatch(entry, /href=["']\/cards\//);
  assert.match(entry, /localizedHref\("\/cards\/members\/"\)/);
  assert.match(entry, /localizedHref\("\/cards\/supports\/"\)/);
  for (const source of [memberTile, supportTile]) {
    assert.match(source, /siteHref\(logicalPath, activeReleaseContext\)/);
    assert.match(source, /activeReleaseContext/);
  }
});

test("card detail navigation preserves locale prefixes and query parameters", async () => {
  const [archive, memberPage, supportPage] = await Promise.all([
    readSource("../src/components/card-details/CardDetailArchive.astro"),
    readSource("../src/pages/cards/members/[id].astro"),
    readSource("../src/pages/cards/supports/[id].astro")
  ]);

  assert.match(archive, /const localizedHref = \(logicalPath: string\)/);
  assert.doesNotMatch(
    archive,
    /href=\{`\/(?:characters|database|resources|tools)\//
  );
  assert.match(
    archive,
    /localizedHref\(`\/tools\/deck-builder\/\?\$\{cardKind/
  );
  assert.match(archive, /localizedHref\(relation\.href\)/);
  for (const page of [memberPage, supportPage]) {
    assert.match(page, /siteHref\(item\.href, activeReleaseContext\)/);
  }
});

test("legacy member-card redirects keep the active locale", async () => {
  const source = await readSource("../src/pages/cards/[id].astro");

  assert.match(
    source,
    /siteHref\(Astro\.props\.target, activeReleaseContext\)/
  );
  assert.match(source, /Astro\.redirect\(\s*redirectTarget,\s*301\s*\)/);
});

test("card links retain logical paths in the root-base development build", async () => {
  const sources = await Promise.all([
    "../src/pages/cards/index.astro",
    "../src/components/MemberCardTile.astro",
    "../src/components/SupportCardTile.astro",
    "../src/components/card-details/CardDetailArchive.astro",
    "../src/pages/cards/members/[id].astro",
    "../src/pages/cards/supports/[id].astro",
    "../src/pages/cards/[id].astro"
  ].map(readSource));

  for (const source of sources) {
    assert.match(source, /import\.meta\.env\.BASE_URL === "\/"/);
  }
});
