#!/usr/bin/env node
// Interactive smoke test for story pages. Confirms spoiler toggle,
// prev/next navigation, URL state restoration, and that metadata-only
// episodes never render a reader.

const fs = require("node:fs");
const path = require("node:path");

const PLAYWRIGHT_PATHS = [
  process.env.OURNOTES_PLAYWRIGHT_MODULE,
  path.resolve(__dirname, '../site/node_modules/playwright'),
  path.resolve(__dirname, '../node_modules/playwright')
].filter(Boolean);

function resolvePlaywright() {
  for (const candidate of PLAYWRIGHT_PATHS) {
    if (fs.existsSync(candidate)) return require(candidate);
  }
  throw new Error("Playwright not found in cache");
}
const PLAYWRIGHT = resolvePlaywright();

const BASE = process.env.STORY_BASE_URL || "http://localhost:4321";

(async () => {
  const browser = await PLAYWRIGHT.chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      errors.push(`${m.type()}: ${m.text()}`);
    }
  });

  const checks = [];

  // 1. Episodes page: spoiler toggle flips data-spoiler-hidden.
  await page.goto(`${BASE}/stories/episodes/story-entry-main-1/`);
  const spoilerBefore = await page.evaluate(() => {
    const node = document.querySelector("[data-spoiler]");
    return node ? node.hasAttribute("data-spoiler-hidden") : null;
  });
  await page.locator("[data-spoiler-toggle]").click();
  const spoilerAfter = await page.evaluate(() => {
    const node = document.querySelector("[data-spoiler]");
    return node ? node.hasAttribute("data-spoiler-hidden") : null;
  });
  checks.push({
    name: "spoiler-toggle",
    pass: spoilerBefore === false && spoilerAfter === true
  });

  // 2. metadata_only entry must NOT have a [data-story-reader] element.
  const hasReader = await page.locator("[data-story-reader]").count();
  checks.push({
    name: "metadata-only-has-no-reader",
    pass: hasReader === 0
  });

  // 3. Prev/next navigation: chapter 1 ep 1 → next must be ep 2.
  const nextHref = await page
    .locator(".story-episode-nav-link--next")
    .first()
    .getAttribute("href");
  checks.push({
    name: "next-link",
    pass: nextHref === "/stories/episodes/story-entry-main-2/"
  });

  // 4. Browser state restoration: open stories index with ?kind=main and
  // confirm only main entries remain visible.
  await page.goto(`${BASE}/stories/?kind=main`);
  await page.waitForSelector("story-browser [data-story-count]");
  const visibleCount = await page.evaluate(() => {
    const browser = document.querySelector("story-browser");
    if (!browser) return null;
    return browser.querySelectorAll(".story-entry-tile:not([hidden])").length;
  });
  const totalMain = await page.evaluate(() => {
    const browser = document.querySelector("story-browser");
    return browser
      ? browser.querySelectorAll('.story-entry-tile[data-kind="main"]').length
      : 0;
  });
  checks.push({
    name: "url-restoration-main-only",
    pass: visibleCount === totalMain && totalMain === 6
  });

  // 5. Episode 1 prev link disabled (it is the first episode).
  await page.goto(`${BASE}/stories/episodes/story-entry-main-1/`);
  const prevDisabled = await page
    .locator(".story-episode-nav-disabled")
    .first()
    .count();
  checks.push({ name: "prev-disabled-at-first-episode", pass: prevDisabled === 1 });

  // 6. Last main episode (story-entry-main-3) — next link should be disabled.
  await page.goto(`${BASE}/stories/episodes/story-entry-main-3/`);
  const nextDisabled = await page.locator(".story-episode-nav-disabled").count();
  checks.push({ name: "next-disabled-at-last-episode", pass: nextDisabled >= 1 });

  // 7. Chapter source card present on chapter page.
  await page.goto(`${BASE}/stories/chapters/story-chapter-1/`);
  const chapterSource = await page.locator(".story-source-list").count();
  checks.push({ name: "chapter-source-card", pass: chapterSource === 1 });

  // 8. Scenes page excludes main entries.
  await page.goto(`${BASE}/stories/scenes/`);
  const sceneTiles = await page.evaluate(() =>
    document.querySelectorAll(".story-entry-tile").length
  );
  const sceneMainTiles = await page.evaluate(() =>
    document.querySelectorAll('.story-entry-tile[data-kind="main"]').length
  );
  checks.push({
    name: "scenes-page-no-main",
    pass: sceneTiles > 0 && sceneMainTiles === 0
  });

  await context.close();
  await browser.close();

  let failures = 0;
  for (const check of checks) {
    if (check.pass) {
      console.log(`ok  ${check.name}`);
    } else {
      failures += 1;
      console.error(`fail ${check.name}`);
    }
  }
  if (errors.length > 0) {
    failures += errors.length;
    for (const error of errors) {
      console.error(`console ${error}`);
    }
  }
  if (failures > 0) {
    console.error(`\n${failures} failure(s).`);
    process.exit(1);
  }
  console.log(`\nAll ${checks.length} interaction checks passed.`);
})();