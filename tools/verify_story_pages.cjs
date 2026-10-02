#!/usr/bin/env node
// Browser verification harness for the story archive module.
// Loads Playwright from the project's local cache, captures console
// messages and failed network requests for each story page, and prints
// a structured summary. Designed to be run after `npm run preview`.

const path = require("node:path");
const fs = require("node:fs");

const PLAYWRIGHT_PATHS = [
  process.env.OURNOTES_PLAYWRIGHT_MODULE,
  path.resolve(__dirname, '../site/node_modules/playwright'),
  path.resolve(__dirname, '../node_modules/playwright')
].filter(Boolean);

function resolvePlaywright() {
  for (const candidate of PLAYWRIGHT_PATHS) {
    if (fs.existsSync(candidate)) {
      return require(candidate);
    }
  }
  throw new Error(
    "Could not locate Playwright in cache; expected one of " +
      PLAYWRIGHT_PATHS.join(", ")
  );
}

const PLAYWRIGHT = resolvePlaywright();

const BASE_URL = process.env.STORY_BASE_URL || "http://localhost:4321";
const ROUTES = [
  { name: "stories-index", path: "/stories/" },
  { name: "stories-chapter", path: "/stories/chapters/story-chapter-1/" },
  { name: "stories-episode", path: "/stories/episodes/story-entry-main-1/" },
  { name: "stories-scenes", path: "/stories/scenes/" }
];

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 }
];

async function verifyRoute(browser, route, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  const warnings = [];
  const failedRequests = [];

  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
    if (msg.type() === "warning") warnings.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    const url = req.url();
    if (url.startsWith("data:") || url.startsWith("blob:")) return;
    failedRequests.push(`${req.method()} ${url} (${req.failure()?.errorText || "?"})`);
  });

  const url = BASE_URL + route.path;
  const response = await page.goto(url, { waitUntil: "networkidle" });
  const status = response ? response.status() : 0;
  const title = await page.title();
  const h1 = await page.locator("h1").first().textContent();
  const hasStatus = await page
    .locator(".status-pill")
    .first()
    .textContent()
    .catch(() => null);

  await context.close();
  return {
    name: `${route.name}@${viewport.name}`,
    url,
    status,
    title: (title || "").trim(),
    h1: (h1 || "").trim(),
    statusPill: (hasStatus || "").trim(),
    errors,
    warnings,
    failedRequests
  };
}

(async () => {
  const browser = await PLAYWRIGHT.chromium.launch();
  const results = [];
  for (const viewport of VIEWPORTS) {
    for (const route of ROUTES) {
      const result = await verifyRoute(browser, route, viewport);
      results.push(result);
      console.log(JSON.stringify(result));
    }
  }
  await browser.close();

  let problems = 0;
  for (const result of results) {
    if (result.status !== 200) problems += 1;
    if (result.errors.length > 0) problems += result.errors.length;
    if (result.warnings.length > 0) problems += result.warnings.length;
    if (result.failedRequests.length > 0) problems += result.failedRequests.length;
  }
  if (problems > 0) {
    console.error(`\nVerification reported ${problems} issue(s).`);
    process.exit(1);
  }
  console.log(`\nAll ${results.length} page/viewport combinations passed.`);
})();