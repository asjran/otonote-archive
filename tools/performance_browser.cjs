#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const childProcess = require("node:child_process");
const {
  assertBaselineWritePolicy,
  createBrowserBaseline,
  digestPerformanceContract,
  evaluateBrowserMeasurement,
  expandBrowserCases,
  isDangerousMediaUrl,
  validateBrowserBaseline,
  writeBrowserBaseline,
} = require("./performance_browser_gate.cjs");

function optionValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  if (!process.argv[index + 1]) throw new Error(`${name} requires a value`);
  return process.argv[index + 1];
}

function resolvePlaywright() {
  if (process.env.PLAYWRIGHT_PATH) return require(process.env.PLAYWRIGHT_PATH);
  const cache = path.join(process.env.HOME || "", ".npm", "_npx");
  if (fs.existsSync(cache)) {
    for (const entry of fs.readdirSync(cache)) {
      const candidate = path.join(cache, entry, "node_modules", "playwright");
      if (fs.existsSync(path.join(candidate, "package.json"))) return require(candidate);
    }
  }
  throw new Error("Playwright is unavailable; run the bundled playwright-cli once or set PLAYWRIGHT_PATH");
}

const baseUrl = process.env.PERF_BASE_URL || "http://127.0.0.1:4321";
const output = optionValue("--output", process.env.PERF_OUTPUT || "site/output/performance/browser.json");
const contractPath = path.resolve(optionValue(
  "--contract",
  process.env.PERF_CONTRACT || path.join(__dirname, "../config/performance/gates.product-v1.json"),
));
const baselineOption = optionValue("--baseline", process.env.PERF_BASELINE || "");
const baselinePath = baselineOption ? path.resolve(baselineOption) : null;
const writeBaseline = process.argv.includes("--write-baseline");
const throttle3Mbps = process.env.PERF_THROTTLE === "1";
const requestedViewport = process.env.PERF_VIEWPORT || "";
const budgetOnly = process.argv.includes("--budget-only");
const performanceUserAgent = "OurNotesPerformanceBrowser/1.0";
const prefix = "/global/zh-CN";
const contractPayload = JSON.parse(fs.readFileSync(contractPath, "utf8"));
const contractDigest = digestPerformanceContract(contractPayload);
const browserCases = expandBrowserCases(contractPayload);
const isLargeMedia = isDangerousMediaUrl;
const isStageAsset = (url) => /\/media\/stage(?:-assets)?\//.test(url);

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

async function applyThrottle(context, page) {
  if (!throttle3Mbps) return;
  const session = await context.newCDPSession(page);
  await session.send("Network.enable");
  await session.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 100,
    downloadThroughput: 375_000,
    uploadThroughput: 125_000,
    connectionType: "cellular3g"
  });
}

async function waitForResourceSettle(page) {
  // A first network-idle can precede IntersectionObserver and dynamic-import
  // work scheduled by the initial layout. Give that work a deterministic
  // chance to start, then require two identical completed-resource samples.
  await page.waitForTimeout(500);
  let previousSignature = null;
  let stableSamples = 0;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await page.waitForLoadState("networkidle", { timeout: 10_000 });
    const snapshot = await page.evaluate(() => {
      const entries = performance.getEntriesByType("resource");
      return {
        count: entries.length,
        signature: entries.map((entry) => [
          entry.name,
          entry.transferSize || 0,
          entry.encodedBodySize || 0,
          entry.responseEnd || 0,
        ]),
      };
    });
    const signature = `${snapshot.count}:${JSON.stringify(snapshot.signature)}`;
    if (signature === previousSignature) {
      stableSamples += 1;
      if (stableSamples >= 2) return;
    } else {
      previousSignature = signature;
      stableSamples = 0;
    }
    await page.waitForTimeout(150);
  }
  throw new Error("resource_measurement_settle_timeout");
}

async function measure(browser, caseDefinition, baselineCase) {
  const viewport = caseDefinition.viewport;
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    userAgent: performanceUserAgent,
  });
  const page = await context.newPage();
  await applyThrottle(context, page);
  const requests = [];
  const requestFailures = [];
  const badResponses = [];
  page.on("request", (request) => requests.push({ url: request.url(), type: request.resourceType() }));
  page.on("requestfailed", (request) => requestFailures.push({ url: request.url(), error: request.failure()?.errorText }));
  page.on("response", (response) => {
    const request = response.request();
    const isMainDocument = request.isNavigationRequest() && request.frame() === page.mainFrame();
    if (response.status() >= 400 && !isMainDocument) {
      badResponses.push({ url: response.url(), status: response.status() });
    }
  });
  const started = Date.now();
  const response = await page.goto(baseUrl + caseDefinition.path, { waitUntil: "networkidle", timeout: 60_000 });
  await waitForResourceSettle(page);
  const elapsedMs = Date.now() - started;
  const entries = await page.evaluate(() => performance.getEntriesByType("resource").map((entry) => ({
    name: entry.name,
    transferSize: entry.transferSize || 0,
    encodedBodySize: entry.encodedBodySize || 0,
    duration: entry.duration || 0
  })));
  const navigation = await page.evaluate(() => {
    const item = performance.getEntriesByType("navigation")[0];
    return item ? {
      transferSize: item.transferSize || 0,
      encodedBodySize: item.encodedBodySize || 0,
      responseStart: item.responseStart || 0,
      domContentLoaded: item.domContentLoadedEventEnd || 0,
      load: item.loadEventEnd || 0
    } : {};
  });
  const bytes = (navigation.transferSize || navigation.encodedBodySize || 0) + entries.reduce(
    (total, entry) => total + (entry.transferSize || entry.encodedBodySize || 0), 0
  );
  const dangerousMedia = requests.filter((request) => isDangerousMediaUrl(request.url));
  const stageAssets = requests.filter((request) => isStageAsset(request.url));
  const measurement = {
    status: response?.status() || 0,
    bytes,
    requestCount: requests.length,
    badResponses,
    requestFailures,
    dangerousMedia,
  };
  const verdict = evaluateBrowserMeasurement(caseDefinition, measurement, baselineCase);
  const reasonCodes = [...verdict.reasonCodes];
  if (caseDefinition.routeId === "music-detail" && stageAssets.length > 0) {
    reasonCodes.push("automatic_stage_asset");
  }
  const result = {
    id: caseDefinition.id,
    name: caseDefinition.id,
    routeId: caseDefinition.routeId,
    locale: caseDefinition.locale,
    path: caseDefinition.path,
    viewport,
    maxBytes: caseDefinition.maxBytes,
    maxRequests: caseDefinition.maxRequests,
    baseline: baselineCase || null,
    ...measurement,
    elapsedMs,
    largeMedia: dangerousMedia,
    stageAssets,
    failures: requestFailures,
    navigation,
    reasonCodes,
    pass: reasonCodes.length === 0,
  };
  await context.close();
  return result;
}

async function measureInteractions(browser) {
  const results = [];

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: performanceUserAgent });
    const page = await context.newPage();
    const requests = [];
    const pageErrors = [];
    page.on("request", (request) => requests.push(request.url()));
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const costumeStageState = () => page.evaluate(() => {
      const canvases = [...document.querySelectorAll("[data-live2d-stage-canvas]")];
      const canvas = canvases[0];
      const image = document.querySelector("[data-costume-stage-image]");
      const placeholder = document.querySelector("[data-costume-stage-placeholder]");
      const startButton = document.querySelector("[data-live2d-start]");
      const rect = canvas?.getBoundingClientRect();
      return {
        canvasCount: canvases.length,
        canvasConnected: Boolean(canvas?.isConnected),
        canvasHidden: Boolean(canvas?.hidden),
        canvasVisible: Boolean(
          canvas && !canvas.hidden && rect && rect.width > 0 && rect.height > 0
        ),
        staticFallbackVisible: Boolean(
          (image && !image.hidden && image.getAttribute("src")) ||
          (placeholder && !placeholder.hidden)
        ),
        state: document.querySelector("[data-costume-stage]")?.dataset.live2dState,
        startDisabled: Boolean(startButton?.disabled),
        startBusy: startButton?.getAttribute("aria-busy")
      };
    });
    const waitForLive2D = () => page.waitForFunction(() => {
      const canvas = document.querySelector("[data-live2d-stage-canvas]");
      const stage = document.querySelector("[data-costume-stage]");
      const rect = canvas?.getBoundingClientRect();
      return stage?.dataset.live2dState === "ready" &&
        canvas?.isConnected && !canvas.hidden && rect && rect.width > 0 && rect.height > 0;
    }, null, { timeout: 45_000 });
    await page.goto(`${baseUrl}${prefix}/characters/character-1/`, { waitUntil: "networkidle" });
    const beforeOpen = requests.length;
    await page.click('[data-character-media-open][data-panel="costumes"]');
    await page.waitForTimeout(750);
    const passiveModels = requests.slice(beforeOpen).filter((url) => /\.model3\.json(?:\?|$)/i.test(url));
    const beforeStart = requests.length;
    await page.click("[data-live2d-start]");
    const firstLoading = await costumeStageState();
    await page.evaluate(() => document.querySelector("[data-live2d-start]")?.click());
    await waitForLive2D();
    const firstReady = await costumeStageState();

    await page.click('dialog[data-panel="costumes"] [data-character-media-close]');
    await page.waitForFunction(() => !document.querySelector('dialog[data-panel="costumes"]')?.open);
    const afterClose = await costumeStageState();

    await page.click('[data-character-media-open][data-panel="costumes"]');
    const afterReopen = await costumeStageState();
    await page.click("[data-live2d-start]");
    await waitForLive2D();
    const reopenedReady = await costumeStageState();

    const switchedCostume = await page.evaluate(() => {
      const target = [...document.querySelectorAll("[data-costume-stage-select]")]
        .find((button) => button.getAttribute("aria-pressed") !== "true" && button.dataset.live2dModelUrl);
      target?.click();
      return target?.dataset.costumeNumber ?? null;
    });
    const afterSwitch = await costumeStageState();
    await page.click("[data-live2d-start]");
    await waitForLive2D();
    const switchedReady = await costumeStageState();

    const startedModels = [...new Set(requests.slice(beforeStart).filter((url) => /\.model3\.json(?:\?|$)/i.test(url)))];
    results.push({
      name: "character-costume-live2d-lifecycle",
      passiveModelRequests: passiveModels,
      startedModelRequests: startedModels,
      switchedCostume,
      firstLoading,
      firstReady,
      afterClose,
      afterReopen,
      reopenedReady,
      afterSwitch,
      switchedReady,
      pageErrors,
      pass: passiveModels.length === 0 &&
        startedModels.length >= 2 &&
        firstLoading.state === "loading" && firstLoading.startDisabled && firstLoading.startBusy === "true" &&
        firstReady.canvasVisible && firstReady.canvasCount === 1 &&
        afterClose.canvasConnected && afterClose.canvasHidden && afterClose.staticFallbackVisible &&
        afterReopen.canvasConnected && afterReopen.canvasHidden && afterReopen.startBusy === "false" &&
        reopenedReady.canvasVisible && reopenedReady.canvasCount === 1 &&
        Boolean(switchedCostume) && afterSwitch.canvasConnected && afterSwitch.canvasHidden && afterSwitch.staticFallbackVisible &&
        switchedReady.canvasVisible && switchedReady.canvasCount === 1 &&
        pageErrors.length === 0
    });
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: performanceUserAgent });
    const page = await context.newPage();
    await page.route("**/*.model3.json", (route) => route.fulfill({
      status: 500,
      contentType: "application/json",
      body: "{}"
    }));
    await page.goto(`${baseUrl}${prefix}/characters/character-1/`, { waitUntil: "networkidle" });
    await page.click('[data-character-media-open][data-panel="costumes"]');
    await page.click("[data-live2d-start]");
    await page.waitForFunction(() =>
      document.querySelector("[data-costume-stage]")?.dataset.live2dState === "error"
    );
    const fallback = await page.evaluate(() => {
      const canvas = document.querySelector("[data-live2d-stage-canvas]");
      const image = document.querySelector("[data-costume-stage-image]");
      const placeholder = document.querySelector("[data-costume-stage-placeholder]");
      const startButton = document.querySelector("[data-live2d-start]");
      return {
        canvasCount: document.querySelectorAll("[data-live2d-stage-canvas]").length,
        canvasConnected: Boolean(canvas?.isConnected),
        canvasHidden: Boolean(canvas?.hidden),
        staticFallbackVisible: Boolean(
          (image && !image.hidden && image.getAttribute("src")) ||
          (placeholder && !placeholder.hidden)
        ),
        startDisabled: Boolean(startButton?.disabled),
        startBusy: startButton?.getAttribute("aria-busy")
      };
    });
    results.push({
      name: "character-costume-live2d-fallback",
      fallback,
      pass: fallback.canvasCount === 1 && fallback.canvasConnected && fallback.canvasHidden &&
        fallback.staticFallbackVisible && !fallback.startDisabled && fallback.startBusy === "false"
    });
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: performanceUserAgent });
    const page = await context.newPage();
    const requests = [];
    page.on("request", (request) => requests.push(request.url()));
    await page.goto(`${baseUrl}${prefix}/music/music-100001/`, { waitUntil: "networkidle" });
    const beforeAuto = requests.length;
    await page.click('[data-music-view="auto"]');
    await page.waitForTimeout(2_000);
    const autoRequests = requests.slice(beforeAuto);
    const stageAssets = [...new Set(autoRequests.filter(isStageAsset))];
    const chartData = [...new Set(autoRequests.filter((url) => /\/data\/music-charts\/.+\.json(?:\?|$)/.test(url)))];
    results.push({
      name: "auto-current-theme-intent",
      stageAssetRequests: stageAssets.length,
      chartRequests: chartData,
      pass: stageAssets.length > 0 && stageAssets.length <= 48 && chartData.length === 1
    });
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: performanceUserAgent });
    const page = await context.newPage();
    const requests = [];
    page.on("request", (request) => requests.push(request.url()));
    await page.route(/\.(?:mp4|webm|flac|wav|m4a|mp3|aac)(?:\?.*)?$/i, (route) =>
      route.fulfill({ status: 206, headers: { "Content-Range": "bytes 0-0/1", "Content-Length": "1" }, body: "0" })
    );
    await page.goto(`${baseUrl}${prefix}/resources/media/device/`, { waitUntil: "networkidle" });
    const beforeClick = requests.length;
    await page.click("[data-device-media-load]");
    await page.waitForTimeout(750);
    const mediaRequests = [...new Set(requests.slice(beforeClick).filter(isLargeMedia))];
    results.push({ name: "device-single-media-intent", mediaRequests, pass: mediaRequests.length === 1 });
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: performanceUserAgent });
    const page = await context.newPage();
    const requests = [];
    page.on("request", (request) => requests.push(request.url()));
    await page.goto(`${baseUrl}${prefix}/stories/episodes/story-entry-live_result-1/`, { waitUntil: "networkidle" });
    const backgroundRequests = [...new Set(requests.filter((url) => /\/media\/.+\.(?:png|jpe?g|webp|avif)(?:\?|$)/i.test(url)))];
    results.push({
      name: "story-adjacent-backgrounds",
      backgroundRequests,
      pass: backgroundRequests.length <= 2
    });
    await context.close();
  }

  return results;
}

(async () => {
  if (process.argv.includes("--list-cases")) {
    process.stdout.write(JSON.stringify(browserCases));
    return;
  }
  if (writeBaseline && !baselinePath) {
    throw new Error("baseline_path_required_for_write");
  }
  assertBaselineWritePolicy({ baselinePath, outputPath: output, writeBaseline });
  const runner = process.env.PERF_RUNNER || "";
  if ((baselinePath || writeBaseline) && !runner) {
    throw new Error("baseline_runner_required");
  }
  if (writeBaseline && requestedViewport) {
    throw new Error("baseline_requires_full_case_matrix");
  }
  let baseline = null;
  let baselineCases = new Map();
  if (baselinePath && !writeBaseline) {
    if (!fs.existsSync(baselinePath)) throw new Error("baseline_file_missing");
    baseline = JSON.parse(fs.readFileSync(baselinePath, "utf8"));
    const baselineVerdict = validateBrowserBaseline(baseline, {
      contractDigest,
      runner,
      caseIds: browserCases.map((item) => item.id),
    });
    if (!baselineVerdict.pass) throw new Error(baselineVerdict.reasonCodes.join(","));
    baselineCases = new Map(baseline.cases.map((item) => [item.id, item]));
  }
  const { chromium } = resolvePlaywright();
  const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const executablePath = process.env.PERF_CHROME_PATH || (fs.existsSync(systemChrome) ? systemChrome : undefined);
  const browser = await chromium.launch({ headless: true, executablePath });
  const selectedCases = requestedViewport
    ? browserCases.filter((item) => item.viewport.name === requestedViewport)
    : browserCases;
  if (selectedCases.length === 0) throw new Error(`Unknown PERF_VIEWPORT: ${requestedViewport}`);
  const results = [];
  for (const caseDefinition of selectedCases) {
    const result = await measure(browser, caseDefinition, baselineCases.get(caseDefinition.id));
    results.push(result);
    process.stdout.write(`${result.pass ? "ok" : "fail"} ${result.name} ${result.bytes} bytes ${result.requestCount} requests${result.reasonCodes.length ? ` [${result.reasonCodes.join(",")}]` : ""}\n`);
  }
  const interactions = (throttle3Mbps || budgetOnly) ? [] : await measureInteractions(browser);
  for (const result of interactions) {
    process.stdout.write(`${result.pass ? "ok" : "fail"} ${result.name}\n`);
  }
  await browser.close();
  const generatedAt = new Date().toISOString();
  const gitHead = resolveGitHead();
  const report = {
    schemaVersion: 2,
    generatedAt,
    gitHead,
    baseUrl,
    contract: path.relative(process.cwd(), contractPath),
    contractDigest,
    runner: runner || "unfixed",
    baseline: baselinePath ? path.relative(process.cwd(), baselinePath) : null,
    writeBaseline,
    budgetOnly,
    throttle3Mbps,
    results,
    interactions,
  };
  const failed = [...results, ...interactions].some((result) => !result.pass);
  const outputIsBaseline = baselinePath && path.resolve(output) === baselinePath;
  if (!outputIsBaseline) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
  }
  if (writeBaseline) {
    if (failed) throw new Error("baseline_source_results_failed");
    writeBrowserBaseline(baselinePath, createBrowserBaseline({
      generatedAt,
      gitHead,
      contractDigest,
      runner,
      results,
    }), { allowWrite: true });
  }
  if (failed) process.exit(1);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
