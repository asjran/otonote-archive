#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const childProcess = require("node:child_process");

const ROUTES = [
  "/global/zh-CN/",
  "/global/zh-CN/catalog/",
  "/global/zh-CN/updates/",
  "/global/zh-CN/characters/",
  "/global/zh-CN/characters/character-1/",
  "/global/zh-CN/cards/",
  "/global/zh-CN/cards/members/",
  "/global/zh-CN/cards/members/member-card-1/",
  "/global/zh-CN/cards/supports/",
  "/global/zh-CN/cards/supports/support-card-1/",
  "/global/zh-CN/database/",
  "/global/zh-CN/database/items/",
  "/global/zh-CN/database/items/item-1/",
  "/global/zh-CN/database/skills/",
  "/global/zh-CN/database/skills/leader-skill-1/",
  "/global/zh-CN/database/band-items/",
  "/global/zh-CN/music/",
  "/global/zh-CN/music/music-100001/",
  "/global/zh-CN/stories/",
  "/global/zh-CN/tools/",
  "/global/zh-CN/tools/deck-builder/",
  "/global/zh-CN/tools/optimizer/",
  "/global/zh-CN/tools/song-calculator/",
  "/global/zh-CN/events/",
  "/global/zh-CN/tools/gekisou-lab/",
];

function resolvePlaywright() {
  if (process.env.PLAYWRIGHT_PATH) return require(process.env.PLAYWRIGHT_PATH);
  const cache = path.join(process.env.HOME || "", ".npm", "_npx");
  if (fs.existsSync(cache)) {
    for (const entry of fs.readdirSync(cache)) {
      const candidate = path.join(cache, entry, "node_modules", "playwright");
      if (fs.existsSync(path.join(candidate, "package.json"))) return require(candidate);
    }
  }
  throw new Error("Playwright is unavailable; run the bundled playwright CLI once or set PLAYWRIGHT_PATH");
}

function resolveGitHead() {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA;
  try {
    return childProcess.execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: path.join(__dirname, ".."),
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "unknown";
  }
}

function releasePathExists(distRoot, href, baseUrl) {
  const url = new URL(href, baseUrl);
  if (url.origin !== new URL(baseUrl).origin) return true;
  const pathname = decodeURIComponent(url.pathname);
  if (pathname.includes("..")) return false;
  const relative = pathname.replace(/^\/+/, "");
  const candidate = path.join(distRoot, relative);
  return fs.existsSync(candidate) || fs.existsSync(path.join(candidate, "index.html"));
}

async function inspectRoute(page, route, viewportName, baseUrl, distRoot) {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const badResponses = [];
  const requests = [];
  const listeners = {
    console: (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    },
    pageerror: (error) => pageErrors.push(String(error)),
    requestfailed: (request) => failedRequests.push({
      url: request.url(),
      error: request.failure()?.errorText || "unknown",
    }),
    response: (response) => {
      if (response.status() >= 400) badResponses.push({ url: response.url(), status: response.status() });
    },
    request: (request) => requests.push(request.url()),
  };
  for (const [event, listener] of Object.entries(listeners)) page.on(event, listener);

  const started = Date.now();
  let response;
  let navigationError = null;
  try {
    response = await page.goto(baseUrl + route, { waitUntil: "networkidle", timeout: 60_000 });
  } catch (error) {
    navigationError = String(error);
  }
  const layout = await page.evaluate(() => {
    const root = document.documentElement;
    const visibleImages = [...document.images].filter((image) => {
      const rect = image.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.top < window.innerHeight && rect.bottom > 0;
    });
    return {
      title: document.title,
      bodyTextLength: document.body?.innerText.trim().length || 0,
      horizontalOverflowPx: Math.max(0, root.scrollWidth - root.clientWidth),
      brokenVisibleImages: visibleImages
        .filter((image) => image.complete && image.naturalWidth === 0)
        .map((image) => image.currentSrc || image.src),
      links: [...document.querySelectorAll("a[href]")].map((anchor) => anchor.href),
    };
  }).catch(() => ({
    title: "",
    bodyTextLength: 0,
    horizontalOverflowPx: 0,
    brokenVisibleImages: [],
    links: [],
  }));
  for (const [event, listener] of Object.entries(listeners)) page.off(event, listener);

  const brokenLinks = [...new Set(layout.links)]
    .filter((href) => !releasePathExists(distRoot, href, baseUrl));
  const forbiddenRequests = [...new Set(requests)].filter((url) =>
    /game-database\.json|\/media\/(?:originals|audio|live2d)\//i.test(url)
  );
  const statusCode = response?.status() || 0;
  const pass = navigationError === null
    && statusCode === 200
    && consoleErrors.length === 0
    && pageErrors.length === 0
    && failedRequests.length === 0
    && badResponses.length === 0
    && layout.bodyTextLength > 20
    && layout.horizontalOverflowPx <= 1
    && layout.brokenVisibleImages.length === 0
    && brokenLinks.length === 0
    && forbiddenRequests.length === 0;
  return {
    route,
    viewport: viewportName,
    statusCode,
    durationMs: Date.now() - started,
    title: layout.title,
    bodyTextLength: layout.bodyTextLength,
    horizontalOverflowPx: layout.horizontalOverflowPx,
    requestCount: requests.length,
    consoleErrors,
    pageErrors,
    failedRequests,
    badResponses,
    brokenVisibleImages: layout.brokenVisibleImages,
    brokenLinks,
    forbiddenRequests,
    navigationError,
    pass,
  };
}

async function main() {
  if (process.argv.includes("--list-routes")) {
    process.stdout.write(JSON.stringify(ROUTES));
    return;
  }
  if (ROUTES.length !== 37 || new Set(ROUTES).size !== ROUTES.length) {
    throw new Error(`expected 37 unique regression routes, got ${ROUTES.length}`);
  }
  const { chromium } = resolvePlaywright();
  const baseUrl = process.env.BROWSER_BASE_URL || "http://127.0.0.1:8765";
  const output = process.env.BROWSER_OUTPUT || "output/readiness/browser-regression.json";
  const distRoot = path.resolve(process.env.BROWSER_DIST_ROOT || "output/release-builds/global-production-current/site");
  const artifactRoot = path.resolve(process.env.BROWSER_ARTIFACT_ROOT || "output/playwright");
  const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const executablePath = process.env.BROWSER_CHROME_PATH
    || (fs.existsSync(systemChrome) ? systemChrome : undefined);
  const browser = await chromium.launch({ headless: true, executablePath });
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 },
  ];
  const results = [];
  fs.mkdirSync(artifactRoot, { recursive: true });
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      userAgent: "OurNotesRegressionBrowser/1.0",
    });
    const page = await context.newPage();
    for (const route of ROUTES) {
      const result = await inspectRoute(page, route, viewport.name, baseUrl, distRoot);
      results.push(result);
      process.stdout.write(`${result.pass ? "ok" : "fail"} ${viewport.name} ${route}\n`);
      if (route === ROUTES[0]) {
        await page.screenshot({
          path: path.join(artifactRoot, `home-${viewport.name}.png`),
          fullPage: true,
        });
      }
    }
    await context.close();
  }
  await browser.close();
  const failures = results.filter((result) => !result.pass);
  const report = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    gitHead: resolveGitHead(),
    status: failures.length === 0 ? "passed" : "failed",
    baseUrl,
    routeCount: ROUTES.length,
    viewportCount: viewports.length,
    checkCount: results.length,
    routes: ROUTES,
    viewports,
    failures,
    results,
    screenshots: viewports.map((viewport) => `output/playwright/home-${viewport.name}.png`),
  };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  if (failures.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
